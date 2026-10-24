import assert from "node:assert/strict";
import test from "node:test";

import { createProductWithListing, waitForExecution } from "../src/actions.js";
import { api, ApiError, requestJson } from "../src/api.js";

function jsonResponse(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() {
      return payload;
    },
  };
}

test("API client uses same-origin paths and reports structured API errors", async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return jsonResponse({ detail: "La tienda todavía no tiene integración." }, 409);
  };
  try {
    await assert.rejects(
      api.updateProduct(7),
      (error) => error instanceof ApiError
        && error.status === 409
        && error.message === "La tienda todavía no tiene integración.",
    );
    assert.equal(requests[0].url, "/api/products/7/update");
    assert.equal(requests[0].options.method, "POST");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("product creation workflow registers a URL without submitting any price", async () => {
  const calls = [];
  const client = {
    async createProduct(product) {
      calls.push(["product", product]);
      return { id: 31, ...product };
    },
    async createListing(productId, listing) {
      calls.push(["listing", productId, listing]);
      return { id: 42, product_id: productId, validation_status: "pending" };
    },
  };
  const result = await createProductWithListing(client, {
    product: { name: "Cámara", canonical_key: "camara" },
    listing: { store_name: "Tienda", source_url: "https://shop.example/item" },
  });

  assert.equal(result.product.id, 31);
  assert.equal(result.listing.validation_status, "pending");
  assert.deepEqual(calls.map(([kind]) => kind), ["product", "listing"]);
  assert.equal(calls[1][1], 31);
  assert.equal(Object.hasOwn(calls[1][2], "amount_minor"), false);
});

test("existing product receives a second URL through the listing endpoint", async () => {
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return jsonResponse({ id: 12, product_id: 4, validation_status: "pending" }, 201);
  };
  try {
    const listing = await api.createListing(4, {
      store_name: "Otra tienda",
      source_url: "https://second.example.test/product",
      title: null,
    });
    assert.equal(listing.product_id, 4);
    assert.equal(request.url, "/api/products/4/listings");
    assert.equal(request.options.method, "POST");
    assert.equal(Object.hasOwn(JSON.parse(request.options.body), "amount_minor"), false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("listing API failure identifies the product that was already created", async () => {
  const product = { id: 9, name: "Lámpara" };
  const expectedError = new Error("URL rechazada");
  const client = {
    async createProduct() {
      return product;
    },
    async createListing() {
      throw expectedError;
    },
  };
  await assert.rejects(
    createProductWithListing(client, {
      product: { name: product.name },
      listing: { source_url: "invalid" },
    }),
    (error) => error === expectedError && error.createdProduct === product,
  );
});

test("update workflow waits for persisted terminal status instead of assuming success", async () => {
  let polls = 0;
  const client = {
    async getExecution(runId) {
      assert.equal(runId, 15);
      polls += 1;
      return {
        id: runId,
        status: "failed",
        errors: ["AdapterNotReadyError"],
      };
    },
  };
  const result = await waitForExecution(
    client,
    { id: 15, status: "running" },
    { intervalMs: 0, sleep: async () => {} },
  );

  assert.equal(polls, 1);
  assert.equal(result.status, "failed");
  assert.deepEqual(result.errors, ["AdapterNotReadyError"]);
});

test("request client surfaces connection errors as a local API error", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    throw new TypeError("offline");
  };
  try {
    await assert.rejects(
      requestJson("/health"),
      (error) => error instanceof ApiError
        && error.status === 0
        && error.message.includes("API local"),
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
