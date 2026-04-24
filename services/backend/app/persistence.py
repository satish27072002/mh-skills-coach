from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Iterator, Sequence

from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    ChannelVersions,
    get_checkpoint_id,
    get_checkpoint_metadata,
    RunnableConfig,
)
from sqlalchemy import delete, func, select

from . import db
from .models import (
    GraphCheckpoint,
    GraphCheckpointBlob,
    GraphCheckpointWrite,
    GuestSessionUsage,
    RateLimitEvent,
)


class DatabaseCheckpointSaver(BaseCheckpointSaver[str]):
    def _ensure_tables(self) -> None:
        db.init_db()

    def _load_blobs(self, thread_id: str, checkpoint_ns: str, versions: ChannelVersions) -> dict[str, Any]:
        self._ensure_tables()
        if not versions:
            return {}
        with db.SessionLocal() as session:
            rows = session.execute(
                select(GraphCheckpointBlob).where(
                    GraphCheckpointBlob.thread_id == thread_id,
                    GraphCheckpointBlob.checkpoint_ns == checkpoint_ns,
                )
            ).scalars()
            blob_map = {(row.channel, row.version): row for row in rows}
        channel_values: dict[str, Any] = {}
        for channel, version in versions.items():
            row = blob_map.get((channel, str(version)))
            if row and row.value_type != "empty":
                channel_values[channel] = self.serde.loads_typed((row.value_type, row.value_data))
        return channel_values

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        self._ensure_tables()
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = get_checkpoint_id(config)
        with db.SessionLocal() as session:
            query = select(GraphCheckpoint).where(
                GraphCheckpoint.thread_id == thread_id,
                GraphCheckpoint.checkpoint_ns == checkpoint_ns,
            )
            if checkpoint_id:
                query = query.where(GraphCheckpoint.checkpoint_id == checkpoint_id)
            else:
                query = query.order_by(GraphCheckpoint.checkpoint_id.desc())
            row = session.execute(query).scalars().first()
            if row is None:
                return None
            writes = session.execute(
                select(GraphCheckpointWrite).where(
                    GraphCheckpointWrite.thread_id == thread_id,
                    GraphCheckpointWrite.checkpoint_ns == checkpoint_ns,
                    GraphCheckpointWrite.checkpoint_id == row.checkpoint_id,
                ).order_by(GraphCheckpointWrite.task_id, GraphCheckpointWrite.write_idx)
            ).scalars().all()
        checkpoint = self.serde.loads_typed((row.checkpoint_type, row.checkpoint_data))
        metadata = self.serde.loads_typed((row.metadata_type, row.metadata_data))
        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": row.checkpoint_id,
                }
            },
            checkpoint={
                **checkpoint,
                "channel_values": self._load_blobs(thread_id, checkpoint_ns, checkpoint["channel_versions"]),
            },
            metadata=metadata,
            pending_writes=[
                (write.task_id, write.channel, self.serde.loads_typed((write.value_type, write.value_data)))
                for write in writes
            ],
            parent_config=(
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": row.parent_checkpoint_id,
                    }
                }
                if row.parent_checkpoint_id
                else None
            ),
        )

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        self._ensure_tables()
        with db.SessionLocal() as session:
            query = select(GraphCheckpoint)
            if config:
                query = query.where(GraphCheckpoint.thread_id == config["configurable"]["thread_id"])
                query = query.where(GraphCheckpoint.checkpoint_ns == config["configurable"].get("checkpoint_ns", ""))
                if checkpoint_id := get_checkpoint_id(config):
                    query = query.where(GraphCheckpoint.checkpoint_id == checkpoint_id)
            if before and (before_id := get_checkpoint_id(before)):
                query = query.where(GraphCheckpoint.checkpoint_id < before_id)
            query = query.order_by(GraphCheckpoint.checkpoint_id.desc())
            if limit is not None:
                query = query.limit(limit)
            rows = session.execute(query).scalars().all()
        for row in rows:
            metadata = self.serde.loads_typed((row.metadata_type, row.metadata_data))
            if filter and not all(metadata.get(k) == v for k, v in filter.items()):
                continue
            result = self.get_tuple(
                {
                    "configurable": {
                        "thread_id": row.thread_id,
                        "checkpoint_ns": row.checkpoint_ns,
                        "checkpoint_id": row.checkpoint_id,
                    }
                }
            )
            if result is not None:
                yield result

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        self._ensure_tables()
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_copy = checkpoint.copy()
        values = checkpoint_copy.pop("channel_values")
        checkpoint_type, checkpoint_data = self.serde.dumps_typed(checkpoint_copy)
        metadata_type, metadata_data = self.serde.dumps_typed(get_checkpoint_metadata(config, metadata))
        with db.SessionLocal() as session:
            for channel, version in new_versions.items():
                if channel in values:
                    value_type, value_data = self.serde.dumps_typed(values[channel])
                else:
                    value_type, value_data = ("empty", b"")
                session.merge(
                    GraphCheckpointBlob(
                        thread_id=thread_id,
                        checkpoint_ns=checkpoint_ns,
                        channel=channel,
                        version=str(version),
                        value_type=value_type,
                        value_data=value_data,
                    )
                )
            session.merge(
                GraphCheckpoint(
                    thread_id=thread_id,
                    checkpoint_ns=checkpoint_ns,
                    checkpoint_id=checkpoint["id"],
                    checkpoint_type=checkpoint_type,
                    checkpoint_data=checkpoint_data,
                    metadata_type=metadata_type,
                    metadata_data=metadata_data,
                    parent_checkpoint_id=config["configurable"].get("checkpoint_id"),
                )
            )
            session.commit()
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        self._ensure_tables()
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]
        with db.SessionLocal() as session:
            existing = {
                (row.task_id, row.write_idx)
                for row in session.execute(
                    select(GraphCheckpointWrite).where(
                        GraphCheckpointWrite.thread_id == thread_id,
                        GraphCheckpointWrite.checkpoint_ns == checkpoint_ns,
                        GraphCheckpointWrite.checkpoint_id == checkpoint_id,
                    )
                ).scalars()
            }
            for index, (channel, value) in enumerate(writes):
                write_idx = WRITES_IDX_MAP.get(channel, index)
                if (task_id, write_idx) in existing and write_idx >= 0:
                    continue
                value_type, value_data = self.serde.dumps_typed(value)
                session.merge(
                    GraphCheckpointWrite(
                        thread_id=thread_id,
                        checkpoint_ns=checkpoint_ns,
                        checkpoint_id=checkpoint_id,
                        task_id=task_id,
                        write_idx=write_idx,
                        channel=channel,
                        value_type=value_type,
                        value_data=value_data,
                        task_path=task_path,
                    )
                )
            session.commit()

    def delete_thread(self, thread_id: str) -> None:
        self._ensure_tables()
        with db.SessionLocal() as session:
            session.execute(delete(GraphCheckpointWrite).where(GraphCheckpointWrite.thread_id == thread_id))
            session.execute(delete(GraphCheckpointBlob).where(GraphCheckpointBlob.thread_id == thread_id))
            session.execute(delete(GraphCheckpoint).where(GraphCheckpoint.thread_id == thread_id))
            session.commit()

    def clear_all(self) -> None:
        self._ensure_tables()
        with db.SessionLocal() as session:
            session.execute(delete(GraphCheckpointWrite))
            session.execute(delete(GraphCheckpointBlob))
            session.execute(delete(GraphCheckpoint))
            session.commit()

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return self.get_tuple(config)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ):
        for item in self.list(config, filter=filter, before=before, limit=limit):
            yield item

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        self.put_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        self.delete_thread(thread_id)


class GuestPromptStore:
    def get_count(self, token: str) -> int:
        db.init_db()
        with db.SessionLocal() as session:
            row = session.get(GuestSessionUsage, token)
            return int(row.prompt_count) if row else 0

    def initialize(self, token: str) -> None:
        db.init_db()
        with db.SessionLocal() as session:
            session.merge(GuestSessionUsage(token=token, prompt_count=0))
            session.commit()

    def increment(self, token: str) -> int:
        db.init_db()
        with db.SessionLocal() as session:
            row = session.get(GuestSessionUsage, token)
            if row is None:
                row = GuestSessionUsage(token=token, prompt_count=0)
                session.add(row)
            row.prompt_count += 1
            session.commit()
            return int(row.prompt_count)

    def delete(self, token: str) -> None:
        db.init_db()
        with db.SessionLocal() as session:
            row = session.get(GuestSessionUsage, token)
            if row is not None:
                session.delete(row)
                session.commit()

    def clear_all(self) -> None:
        db.init_db()
        with db.SessionLocal() as session:
            session.execute(delete(GuestSessionUsage))
            session.commit()


class RateLimitExceeded(Exception):
    def __init__(self, client_key: str, limit: int, window: int) -> None:
        self.client_key = client_key
        self.limit = limit
        self.window = window
        super().__init__(f"Rate limit exceeded for {client_key!r}: max {limit} requests per {window}s")


class DurableRateLimiter:
    def __init__(self, max_requests: int = 10, window_seconds: int = 60, route_key: str = "chat") -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be >= 1")
        if window_seconds < 1:
            raise ValueError("window_seconds must be >= 1")
        self._max_requests = max_requests
        self._window = window_seconds
        self._route_key = route_key

    def _cutoff(self) -> datetime:
        return datetime.now(UTC) - timedelta(seconds=self._window)

    def check(self, client_key: str) -> None:
        db.init_db()
        cutoff = self._cutoff()
        with db.SessionLocal() as session:
            session.execute(delete(RateLimitEvent).where(RateLimitEvent.created_at < cutoff))
            current = session.execute(
                select(func.count()).select_from(RateLimitEvent).where(
                    RateLimitEvent.client_key == client_key,
                    RateLimitEvent.route_key == self._route_key,
                    RateLimitEvent.created_at >= cutoff,
                )
            ).scalar_one()
            if int(current) >= self._max_requests:
                session.commit()
                raise RateLimitExceeded(client_key=client_key, limit=self._max_requests, window=self._window)
            session.add(RateLimitEvent(client_key=client_key, route_key=self._route_key))
            session.commit()

    def remaining(self, client_key: str) -> int:
        db.init_db()
        cutoff = self._cutoff()
        with db.SessionLocal() as session:
            current = session.execute(
                select(func.count()).select_from(RateLimitEvent).where(
                    RateLimitEvent.client_key == client_key,
                    RateLimitEvent.route_key == self._route_key,
                    RateLimitEvent.created_at >= cutoff,
                )
            ).scalar_one()
        return max(0, self._max_requests - int(current))

    def reset(self, client_key: str) -> None:
        db.init_db()
        with db.SessionLocal() as session:
            session.execute(
                delete(RateLimitEvent).where(
                    RateLimitEvent.client_key == client_key,
                    RateLimitEvent.route_key == self._route_key,
                )
            )
            session.commit()

    def clear_all(self) -> None:
        db.init_db()
        with db.SessionLocal() as session:
            session.execute(delete(RateLimitEvent).where(RateLimitEvent.route_key == self._route_key))
            session.commit()

    def purge_expired(self) -> int:
        db.init_db()
        cutoff = self._cutoff()
        with db.SessionLocal() as session:
            rows = session.execute(delete(RateLimitEvent).where(RateLimitEvent.created_at < cutoff))
            session.commit()
            return int(rows.rowcount or 0)
