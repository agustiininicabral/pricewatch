export async function createProductWithListing(client, { product, listing }) {
  const createdProduct = await client.createProduct(product);
  try {
    const createdListing = await client.createListing(createdProduct.id, listing);
    return { product: createdProduct, listing: createdListing };
  } catch (error) {
    error.createdProduct = createdProduct;
    throw error;
  }
}

export async function waitForExecution(
  client,
  initialRun,
  { intervalMs = 500, timeoutMs = 30_000, sleep = delay } = {},
) {
  const deadline = Date.now() + timeoutMs;
  let execution = initialRun;
  while (execution.status === "running") {
    if (Date.now() >= deadline) {
      throw new Error("La actualización sigue en curso. Consultá el panel nuevamente.");
    }
    await sleep(intervalMs);
    execution = await client.getExecution(initialRun.id);
  }
  return execution;
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}
