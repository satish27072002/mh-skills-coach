import { NextResponse } from "next/server";

const DEV_DEFAULT_BASE_URL = "http://localhost:8000";
const PROD_SERVER_BASE_URL = "http://backend:8000";
const PROD_PUBLIC_BASE_URL = "/api";

const isProduction = process.env.NODE_ENV === "production";

const normalizeBaseUrl = (rawValue?: string): string | null => {
  if (!rawValue) {
    return null;
  }
  const trimmed = rawValue.trim();
  if (!trimmed) {
    return null;
  }
  if (trimmed.startsWith("/")) {
    return trimmed.replace(/\/$/, "");
  }
  const withoutTrailingSlash = trimmed.replace(/\/$/, "");
  const withoutStatus = withoutTrailingSlash.replace(/\/status$/, "");
  return withoutStatus.replace(/\/$/, "");
};

const getDefaultPublicBaseUrl = () => (isProduction ? PROD_PUBLIC_BASE_URL : DEV_DEFAULT_BASE_URL);

const getDefaultServerBaseUrl = () => (isProduction ? PROD_SERVER_BASE_URL : DEV_DEFAULT_BASE_URL);

export const getBackendBaseUrl = () => {
  const preferredBase =
    process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? getDefaultPublicBaseUrl();
  const normalized = normalizeBaseUrl(preferredBase);
  if (normalized && !normalized.startsWith("/")) {
    return normalized;
  }
  return getDefaultServerBaseUrl();
};

export const getBackendAuthStartUrl = () => `${getBackendBaseUrl()}/auth/google/start`;

export const copyCookieHeader = (request: Request): string | undefined => {
  const cookie = request.headers.get("cookie");
  return cookie && cookie.trim() ? cookie : undefined;
};

type HeadersWithSetCookie = Headers & {
  getSetCookie?: () => string[];
};

const splitSetCookieHeader = (headerValue: string): string[] => {
  // Split only on cookie boundaries, not the comma in Expires=Wed, ...
  return headerValue
    .split(/,(?=\s*[^;,=\s]+=[^;,]+)/g)
    .map((value) => value.trim())
    .filter(Boolean);
};

export const getSetCookieHeaders = (headers: Headers): string[] => {
  const cookies = (headers as HeadersWithSetCookie).getSetCookie?.();
  if (cookies && cookies.length > 0) {
    return cookies;
  }
  const combined = headers.get("set-cookie");
  if (!combined) {
    return [];
  }
  return splitSetCookieHeader(combined);
};

export const proxyJsonResponse = async (response: Response) => {
  const contentType = response.headers.get("content-type") ?? "application/json";
  const bodyText = await response.text();
  const proxied = new NextResponse(bodyText, {
    status: response.status,
    headers: { "content-type": contentType }
  });
  for (const setCookie of getSetCookieHeaders(response.headers)) {
    proxied.headers.append("set-cookie", setCookie);
  }
  return proxied;
};
