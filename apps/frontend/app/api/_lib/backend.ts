const DEFAULT_BASE_URL = "http://localhost:8000";

const normalizeBaseUrl = (rawValue?: string) => {
  if (!rawValue) {
    return DEFAULT_BASE_URL;
  }
  const trimmed = rawValue.trim();
  if (!trimmed) {
    return DEFAULT_BASE_URL;
  }
  const withoutTrailingSlash = trimmed.replace(/\/$/, "");
  const withoutStatus = withoutTrailingSlash.replace(/\/status$/, "");
  return withoutStatus.replace(/\/$/, "");
};

export const getBackendBaseUrl = () =>
  normalizeBaseUrl(process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL);

export const getBackendAuthStartUrl = () => `${getBackendBaseUrl()}/auth/google/start`;

export const copyCookieHeader = (request: Request): string | undefined => {
  const cookie = request.headers.get("cookie");
  return cookie && cookie.trim() ? cookie : undefined;
};

export const proxyJsonResponse = async (response: Response) => {
  const contentType = response.headers.get("content-type") ?? "application/json";
  const bodyText = await response.text();
  return new Response(bodyText, {
    status: response.status,
    headers: { "content-type": contentType }
  });
};
