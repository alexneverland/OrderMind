const BASE = import.meta.env.VITE_API_BASE_URL || "/api/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function detailMessage(detail: unknown, status: number): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail))
    return detail
      .map((item) =>
        typeof item?.msg === "string" ? item.msg : "Invalid input",
      )
      .join("; ");
  return (
    (
      {
        400: "Please check the supplied values.",
        404: "The item was not found.",
        409: "This item changed. Reload and try again.",
        413: "The input is too large.",
        500: "The server could not complete the request.",
        503: "The database is busy. Try again shortly.",
      } as Record<number, string>
    )[status] || `Request failed (${status}).`
  );
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...options,
      headers: {
        ...(options.body && !(options.body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...options.headers,
      },
    });
  } catch {
    throw new ApiError(
      0,
      "Cannot reach the OrderMind API. Check that the backend is running.",
    );
  }
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json()).detail;
    } catch {
      /* a non-JSON server error */
    }
    throw new ApiError(response.status, detailMessage(detail, response.status));
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function download(
  path: string,
): Promise<{ blob: Blob; filename: string }> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { method: "POST" });
  } catch {
    throw new ApiError(0, "Cannot reach the OrderMind API.");
  }
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json()).detail;
    } catch {
      /* non-JSON response */
    }
    throw new ApiError(response.status, detailMessage(detail, response.status));
  }
  const disposition = response.headers.get("Content-Disposition") || "";
  const filename =
    disposition.match(/filename="?([^";]+)"?/i)?.[1] || "order-export";
  return { blob: await response.blob(), filename };
}

export function saveDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
