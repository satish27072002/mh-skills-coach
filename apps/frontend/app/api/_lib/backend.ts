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

export const proxyJsonResponse = async (response: Response) => {
  const contentType = response.headers.get("content-type") ?? "application/json";
  const bodyText = await response.text();
  const headers = new Headers();
  headers.set("content-type", contentType);
  const setCookie = response.headers.get("set-cookie");
  if (setCookie) {
    headers.set("set-cookie", setCookie);
  }
  return new Response(bodyText, {
    status: response.status,
    headers
  });
};
