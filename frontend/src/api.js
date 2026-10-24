const API_PREFIX = "/api";

export class ApiError extends Error {
  constructor(status, message, payload) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

export async function requestJson(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_PREFIX}${path}`, {
      ...options,
      headers: {
        Accept: "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...options.headers,
      },
    });
  } catch (error) {
    throw new ApiError(0, "No se pudo conectar con la API local.", error);
  }

  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.detail;
    const message = typeof detail === "string"
      ? detail
      : `La API respondió con el estado ${response.status}.`;
    throw new ApiError(response.status, message, payload);
  }
  return payload;
}

function jsonBody(method, body) {
  return { method, body: JSON.stringify(body) };
}

export const api = {
  health: () => requestJson("/health"),
  listProducts: () => requestJson("/products"),
  createProduct: (product) => requestJson("/products", jsonBody("POST", product)),
  deactivateProduct: (productId) =>
    requestJson(`/products/${productId}`, { method: "DELETE" }),
  listListings: (productId) => requestJson(`/products/${productId}/listings`),
  createListing: (productId, listing) =>
    requestJson(`/products/${productId}/listings`, jsonBody("POST", listing)),
  history: (productId, listingId) => {
    const query = listingId ? `?listing_id=${encodeURIComponent(listingId)}` : "";
    return requestJson(`/products/${productId}/history${query}`);
  },
  comparison: (productId) => requestJson(`/products/${productId}/comparison`),
  latestExecution: (productId) => {
    const query = productId ? `?product_id=${encodeURIComponent(productId)}` : "";
    return requestJson(`/executions/latest${query}`);
  },
  updateProduct: (productId) =>
    requestJson(`/products/${productId}/update`, { method: "POST" }),
  updateListing: (listingId) =>
    requestJson(`/listings/${listingId}/update`, { method: "POST" }),
  getExecution: (runId) => requestJson(`/executions/${runId}`),
};
