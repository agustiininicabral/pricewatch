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

export async function storeSlugFromDomain(domain) {
  const slug = domain.replaceAll(".", "-");
  if (slug.length <= 80) return slug;
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(domain),
  );
  const suffix = [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("")
    .slice(0, 12);
  return `${slug.slice(0, 67).replace(/-+$/, "")}-${suffix}`;
}

export function amountToMinorUnits(value, currency, { allowZero = false } = {}) {
  const amount = value.trim();
  const normalizedCurrency = currency.trim().toUpperCase();
  if (!/^[A-Z]{3}$/.test(normalizedCurrency)) {
    throw new Error("Ingresá un código de moneda válido, por ejemplo ARS.");
  }
  if (!/^\d+(?:[.,]\d+)?$/.test(amount)) {
    throw new Error("Ingresá un importe decimal sin separadores de miles.");
  }

  let digits;
  try {
    digits = new Intl.NumberFormat("en", {
      style: "currency",
      currency: normalizedCurrency,
    }).resolvedOptions().maximumFractionDigits;
  } catch {
    throw new Error("La moneda ingresada no es válida.");
  }

  const [whole, fraction = ""] = amount.replace(",", ".").split(".");
  if (fraction.length > digits) {
    throw new Error(`La moneda ${normalizedCurrency} admite hasta ${digits} decimales.`);
  }
  const scale = 10n ** BigInt(digits);
  const minor = BigInt(whole) * scale
    + BigInt(fraction.padEnd(digits, "0") || "0");
  if ((!allowZero && minor <= 0n) || (allowZero && minor < 0n)) {
    throw new Error(allowZero ? "El importe no puede ser negativo." : "El precio debe ser mayor que cero.");
  }
  if (minor > BigInt(Number.MAX_SAFE_INTEGER)) {
    throw new Error("El importe supera el máximo admitido.");
  }
  return Number(minor);
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
