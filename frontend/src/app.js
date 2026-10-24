import { api, ApiError } from "./api.js";
import {
  amountToMinorUnits,
  createProductWithListing,
  storeSlugFromDomain,
  waitForExecution,
} from "./actions.js";

const state = {
  products: [],
  summaries: new Map(),
  selectedProductId: null,
  pendingDeactivateId: null,
};

const elements = {
  apiStatus: document.querySelector("#api-status"),
  globalMessage: document.querySelector("#global-message"),
  productCount: document.querySelector("#product-count"),
  listingCount: document.querySelector("#listing-count"),
  lastUpdate: document.querySelector("#last-update"),
  lastUpdateNote: document.querySelector("#last-update-note"),
  loading: document.querySelector("#products-loading"),
  empty: document.querySelector("#products-empty"),
  noResults: document.querySelector("#products-no-results"),
  table: document.querySelector("#products-table"),
  productsBody: document.querySelector("#products-body"),
  search: document.querySelector("#search-input"),
  form: document.querySelector("#add-form"),
  productMode: document.querySelector("#product-mode"),
  newProductFields: document.querySelector("#new-product-fields"),
  existingProductFields: document.querySelector("#existing-product-fields"),
  existingProductSelect: document.querySelector("#existing-product-id"),
  formMessage: document.querySelector("#form-message"),
  submitButton: document.querySelector("#submit-button"),
  detailPanel: document.querySelector("#detail-panel"),
  detailHeading: document.querySelector("#detail-heading"),
  detailSummary: document.querySelector("#detail-summary"),
  detailLoading: document.querySelector("#detail-loading"),
  detailContent: document.querySelector("#detail-content"),
  confirmDialog: document.querySelector("#confirm-dialog"),
  confirmDeactivate: document.querySelector("#confirm-deactivate"),
};

const statusLabels = {
  verified: "Verificado",
  pending_review: "Pendiente de revisión",
  pending: "Pendiente",
  valid: "Validada",
  invalid: "No validada",
  running: "En curso",
  queued: "En cola",
  succeeded: "Correcta",
  partial: "Parcial",
  failed: "Fallida",
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

function formatDate(value, withTime = true) {
  if (!value) return "Sin datos";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Fecha no disponible";
  return new Intl.DateTimeFormat("es-AR", {
    timeZone: "America/Argentina/Buenos_Aires",
    dateStyle: "medium",
    ...(withTime ? { timeStyle: "short" } : {}),
  }).format(date);
}

function formatMoney(amountMinor, currency) {
  if (amountMinor === null || amountMinor === undefined || !currency) return "No disponible";
  try {
    const formatter = new Intl.NumberFormat("es-AR", {
      style: "currency",
      currency,
    });
    const digits = formatter.resolvedOptions().maximumFractionDigits;
    const amount = BigInt(amountMinor);
    const scale = 10n ** BigInt(digits);
    const whole = amount / scale;
    const fraction = (amount % scale).toString().padStart(digits, "0");
    const wholeText = new Intl.NumberFormat("es-AR", {
      maximumFractionDigits: 0,
    }).format(whole);
    const zeroParts = formatter.formatToParts(0);
    const decimal = formatter.formatToParts(1.1).find((part) => part.type === "decimal")?.value ?? ",";
    let insertedNumber = false;
    return zeroParts.map((part) => {
      if (part.type === "integer") {
        insertedNumber = true;
        return `${wholeText}${digits ? `${decimal}${fraction}` : ""}`;
      }
      if (part.type === "group" || part.type === "decimal" || part.type === "fraction") {
        return "";
      }
      return part.value;
    }).join("") || (insertedNumber ? "" : `${wholeText}${digits ? `${decimal}${fraction}` : ""} ${currency}`);
  } catch {
    return `${amountMinor} ${currency}`;
  }
}

function statusPill(status, label = statusLabels[status] || status || "Sin datos") {
  const kind = status === "verified" || status === "succeeded"
    ? "verified"
    : status === "failed" || status === "partial" || status === "invalid"
      ? "failed"
      : status === "running" || status === "queued" || status === "pending" || status === "pending_review"
        ? "pending"
        : "";
  return `<span class="status-pill ${kind}">${escapeHtml(label)}</span>`;
}

function latestByListing(history) {
  const latest = new Map();
  for (const observation of history) latest.set(observation.listing_id, observation);
  return latest;
}

function latestExecutionText(execution) {
  if (!execution) return "Sin ejecuciones";
  return `${statusLabels[execution.status] || execution.status} · ${formatDate(execution.completed_at || execution.started_at)}`;
}

async function getOptionalLatestExecution(productId) {
  try {
    return await api.latestExecution(productId);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

async function loadDashboard() {
  elements.loading.hidden = false;
  elements.table.hidden = true;
  elements.empty.hidden = true;
  try {
    await api.health();
    elements.apiStatus.textContent = "API local conectada";
    elements.apiStatus.className = "api-status online";
    const [products, mostRecentExecution] = await Promise.all([
      api.listProducts(),
      getOptionalLatestExecution(),
    ]);
    state.products = products;
    renderExistingProductOptions();
    const summaryEntries = await Promise.all(products.map(async (product) => {
      const [listings, history, execution] = await Promise.all([
        api.listListings(product.id),
        api.history(product.id),
        getOptionalLatestExecution(product.id),
      ]);
      return [product.id, {
        listings,
        history,
        latest: latestByListing(history),
        execution,
      }];
    }));
    state.summaries = new Map(summaryEntries);
    elements.productCount.textContent = String(products.length);
    elements.listingCount.textContent = String(
      summaryEntries.reduce((total, [, summary]) => total + summary.listings.length, 0),
    );
    let globalExecution = mostRecentExecution;
    for (const [, summary] of summaryEntries) {
      if (
        summary.execution
        && (!globalExecution || summary.execution.started_at > globalExecution.started_at)
      ) globalExecution = summary.execution;
    }
    elements.lastUpdate.textContent = globalExecution
      ? latestExecutionText(globalExecution)
      : "Sin ejecuciones";
    elements.lastUpdateNote.textContent = globalExecution
      ? `${globalExecution.listings_checked} publicaciones revisadas`
      : "Las fechas se muestran en hora argentina";
    elements.loading.hidden = true;
    elements.empty.hidden = products.length !== 0;
    elements.table.hidden = products.length === 0;
    renderProducts();
    if (state.selectedProductId) {
      const selected = products.find((item) => item.id === state.selectedProductId);
      if (selected) await showProductDetail(selected);
      else closeProductDetail();
    }
  } catch (error) {
    elements.loading.hidden = true;
    elements.apiStatus.textContent = "API local no disponible";
    elements.apiStatus.className = "api-status offline";
    showGlobalError(error);
  }
}

function productStatus(product, summary) {
  if (!product.is_active) return statusPill("pending", "Desactivado");
  if (summary.execution && ["running", "queued"].includes(summary.execution.status)) {
    return statusPill(summary.execution.status);
  }
  if (summary.execution && ["failed", "partial"].includes(summary.execution.status)) {
    return statusPill(summary.execution.status);
  }
  if (summary.listings.length === 0) return statusPill("pending", "Sin publicaciones");
  const observations = [...summary.latest.values()];
  const verifiedCount = observations.filter((item) => item.validation_status === "verified").length;
  if (verifiedCount === summary.listings.length) {
    return statusPill("verified");
  }
  if (verifiedCount > 0) return statusPill("pending", "Datos mixtos");
  if (observations.some((item) => item.validation_status === "pending_review")) {
    return statusPill("pending_review");
  }
  return statusPill("pending", "Fuente no configurada");
}

function renderProducts() {
  const search = elements.search.value.trim().toLocaleLowerCase("es-AR");
  const visibleProducts = state.products.filter((product) =>
    `${product.name} ${product.canonical_key} ${product.brand || ""}`
      .toLocaleLowerCase("es-AR").includes(search),
  );
  elements.noResults.hidden = state.products.length === 0 || visibleProducts.length > 0;
  elements.productsBody.innerHTML = visibleProducts.map((product) => {
    const summary = state.summaries.get(product.id) || { listings: [], latest: new Map() };
    const latestObservation = [...summary.latest.values()]
      .sort((left, right) => right.observed_at.localeCompare(left.observed_at))[0];
    const checkedAt = summary.listings
      .map((listing) => listing.last_checked_at)
      .filter(Boolean)
      .sort()
      .at(-1);
    const lastData = latestObservation
      ? `${formatDate(latestObservation.observed_at)}`
      : checkedAt ? formatDate(checkedAt) : "Sin observaciones";
    const lastDataNote = summary.execution && ["failed", "partial"].includes(summary.execution.status)
      ? latestObservation
        ? "Última consulta fallida; se conserva el precio anterior"
        : "Último intento fallido"
      : latestObservation
        ? statusLabels[latestObservation.validation_status] || latestObservation.validation_status
        : checkedAt ? "Último intento" : "Fecha de observación";
    return `<tr>
      <td><span class="product-name">${escapeHtml(product.name)}</span><span class="product-key">${escapeHtml(product.canonical_key)}</span></td>
      <td><span class="cell-main">${summary.listings.length}</span><span class="cell-note">${summary.listings.length === 1 ? "publicación" : "publicaciones"}</span></td>
      <td><span class="cell-main">${escapeHtml(lastData)}</span><span class="cell-note">${escapeHtml(lastDataNote)}</span></td>
      <td>${productStatus(product, summary)}</td>
      <td><div class="row-actions">
        <button class="link-button" type="button" data-action="detail" data-product-id="${product.id}">Detalle</button>
        <button class="link-button" type="button" data-action="update-product" data-product-id="${product.id}">Actualizar</button>
        <button class="link-button" type="button" data-action="deactivate" data-product-id="${product.id}" aria-label="Desactivar ${escapeHtml(product.name)}">Desactivar</button>
      </div></td>
    </tr>`;
  }).join("");
}

function showGlobalError(error) {
  showGlobalMessage(userFacingError(error), "error");
}

function showGlobalMessage(message, kind = "error") {
  elements.globalMessage.textContent = message;
  elements.globalMessage.classList.toggle("success", kind === "success");
  elements.globalMessage.hidden = false;
}

function userFacingError(error) {
  if (error instanceof ApiError) return error.message;
  return error?.message || "Ocurrió un error inesperado.";
}

function showFormMessage(message, isError = false) {
  elements.formMessage.textContent = message;
  elements.formMessage.classList.toggle("error", isError);
  elements.formMessage.hidden = false;
}

function renderExistingProductOptions() {
  const currentId = elements.existingProductSelect.value;
  elements.existingProductSelect.innerHTML = [
    `<option value="">Seleccioná un producto</option>`,
    ...state.products.map((product) =>
      `<option value="${product.id}">${escapeHtml(product.name)}</option>`),
  ].join("");
  if (state.products.some((product) => String(product.id) === currentId)) {
    elements.existingProductSelect.value = currentId;
  }
  elements.productMode.querySelector('option[value="existing"]').disabled = state.products.length === 0;
  updateProductFormMode();
}

function updateProductFormMode() {
  const isNewProduct = elements.productMode.value === "new";
  elements.newProductFields.hidden = !isNewProduct;
  elements.existingProductFields.hidden = isNewProduct;
  elements.form.elements.name.required = isNewProduct;
  elements.form.elements.canonical_key.required = isNewProduct;
  elements.existingProductSelect.required = !isNewProduct;
}

function escapeAttribute(value) {
  return escapeHtml(value);
}

function comparisonOfferMap(comparison) {
  const offers = new Map();
  for (const group of comparison.groups) {
    for (const offer of group.offers) offers.set(offer.source_url, offer);
  }
  return offers;
}

function renderListings(listings, history, comparison) {
  const latest = latestByListing(history);
  const offers = comparisonOfferMap(comparison);
  const excluded = new Map(comparison.excluded.map((item) => [item.source_url, item.reason]));
  if (!listings.length) {
    return `<div class="chart-empty">No hay publicaciones registradas para este producto.</div>`;
  }
  const rows = listings.map((listing) => {
    const observation = latest.get(listing.id);
    const offer = offers.get(listing.url);
    const exclusionReason = excluded.get(listing.url);
    const availability = observation
      ? observation.availability === "in_stock" ? "Stock confirmado"
        : observation.availability === "out_of_stock" ? "Sin stock" : "Stock desconocido"
      : "Sin observaciones";
    let shipping = "Desconocido";
    let total = "No comparable";
    if (offer) {
      shipping = offer.shipping_status === "free"
        ? "Gratis confirmado"
        : formatMoney(offer.shipping_minor, offer.currency);
      total = formatMoney(offer.total_minor, offer.currency);
    } else if (exclusionReason?.toLocaleLowerCase("es-AR").includes("envío")) {
      shipping = "Desconocido";
    }
    const observationStatus = observation
      ? statusPill(observation.validation_status)
      : statusPill(listing.validation_status, "Pendiente");
    return `<tr>
      <td class="listing-title"><span class="cell-main">${escapeHtml(listing.title || observation?.title || "Publicación sin título")}</span>
        <a class="external-link" href="${escapeAttribute(listing.url)}" target="_blank" rel="noopener noreferrer">Abrir publicación ↗</a></td>
      <td>${observation ? `<span class="cell-main">${formatMoney(observation.amount_minor, observation.currency)}</span><span class="cell-note">${escapeHtml(observation.currency)} · ${formatDate(observation.observed_at)}</span>` : "Sin precio observado"}</td>
      <td>${observationStatus}<span class="cell-note">${escapeHtml(availability)}</span></td>
      <td><span class="cell-main">${escapeHtml(shipping)}</span>${exclusionReason ? `<span class="cell-note">${escapeHtml(exclusionReason)}</span>` : ""}</td>
      <td><span class="cell-main">${escapeHtml(total)}</span></td>
      <td><button class="button button-quiet button-small" type="button" data-action="update-listing" data-listing-id="${listing.id}">Actualizar</button></td>
    </tr>`;
  }).join("");

  const manualEntryForms = listings.map((listing) => {
    const observation = latest.get(listing.id);
    const currency = observation?.currency || "ARS";
    const product = state.products.find((item) => item.id === listing.product_id);
    const title = listing.title || observation?.title || product?.name || "";
    return `<details class="manual-entry">
      <summary>Ingresar precio y envío manualmente · ${escapeHtml(listing.store_name)}</summary>
      <p class="field-help">Copiá los datos que observaste en la publicación. No se consulta la tienda. Solo los datos marcados como comprobados participan de la comparación.</p>
      <form class="manual-entry-form" data-action="manual-observation" data-listing-id="${listing.id}" data-product-id="${listing.product_id}">
        <label>Título observado
          <input name="title" required maxlength="500" value="${escapeAttribute(title)}" placeholder="Nombre del artículo">
        </label>
        <label>Precio
          <input name="amount" type="text" inputmode="decimal" required placeholder="Ej.: 129999,99">
        </label>
        <label>Moneda (ISO)
          <input name="currency" required maxlength="3" pattern="[A-Za-z]{3}" value="${escapeAttribute(currency)}" aria-label="Moneda del precio, por ejemplo ARS">
        </label>
        <label>Disponibilidad observada
          <select name="availability" required>
            <option value="">Seleccionar</option>
            <option value="in_stock">Hay stock</option>
            <option value="out_of_stock">Sin stock</option>
            <option value="unknown">No pude confirmar</option>
          </select>
        </label>
        <label class="manual-verified">
          <input name="verified" type="checkbox">
          Comprobé manualmente el precio, moneda y disponibilidad en esa publicación.
        </label>
        <button class="button button-primary" type="submit">Guardar precio observado</button>
      </form>
      <form class="manual-entry-form shipping-form" data-action="manual-shipping" data-listing-id="${listing.id}" data-product-id="${listing.product_id}">
        <label>Envío
          <select name="shipping_status" required>
            <option value="unknown">No verificado</option>
            <option value="free">Gratis confirmado</option>
            <option value="paid">Tiene costo</option>
          </select>
        </label>
        <label class="shipping-amount-fields" hidden>Importe del envío
          <input name="shipping_amount" type="text" inputmode="decimal" placeholder="Ej.: 2500">
        </label>
        <label class="shipping-amount-fields" hidden>Moneda del envío
          <input name="shipping_currency" required maxlength="3" pattern="[A-Za-z]{3}" value="${escapeAttribute(currency)}">
        </label>
        <label>Fuente del dato
          <input name="shipping_source" required maxlength="120" value="Observado manualmente">
        </label>
        <button class="button button-quiet" type="submit">Guardar envío</button>
      </form>
    </details>`;
  }).join("");

  return `<div class="table-scroll"><table class="listing-table">
    <thead><tr><th>Publicación</th><th>Precio</th><th>Dato</th><th>Envío</th><th>Costo total</th><th></th></tr></thead>
    <tbody>${rows}</tbody>
  </table></div>${manualEntryForms}`;
}

function renderComparison(comparison) {
  if (!comparison.groups.length) {
    return `<p class="comparison-summary">${escapeHtml(comparison.summary)}</p>
      ${comparison.excluded.length
        ? `<ul>${comparison.excluded.map((item) => `<li class="blocking-reason">${escapeHtml(item.reason)}</li>`).join("")}</ul>`
        : `<div class="chart-empty">No hay ofertas verificadas para comparar todavía.</div>`}`;
  }
  return `${comparison.groups.map((group) => {
    const winner = group.cheapest_offer;
    const rows = group.offers.map((offer) => `<tr>
      <td><a class="external-link" href="${escapeAttribute(offer.source_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(offer.title || offer.source_url)}</a></td>
      <td>${formatMoney(offer.price_minor, offer.currency)}</td>
      <td>${offer.shipping_status === "free" ? "Gratis confirmado" : formatMoney(offer.shipping_minor, offer.currency)}</td>
      <td><strong>${formatMoney(offer.total_minor, offer.currency)}</strong></td>
      <td>${offer.difference_from_cheapest_minor === 0 ? "Más económica" : offer.difference_from_cheapest_minor === null ? "Sin ganador definitivo" : `+${formatMoney(offer.difference_from_cheapest_minor, offer.currency)}`}</td>
    </tr>`).join("");
    return `<section class="detail-section">
      <h3>${escapeHtml(group.currency)}${group.variant_key ? ` · Variante ${escapeHtml(group.variant_key)}` : ""}</h3>
      ${winner ? `<p class="winner-note">Menor costo total comparable: ${formatMoney(winner.total_minor, winner.currency)}</p>` : `<p class="comparison-summary">No se puede definir una ganadora con los datos disponibles.</p>`}
      ${group.blocking_reasons.map((reason) => `<p class="blocking-reason">${escapeHtml(reason)}</p>`).join("")}
      <div class="table-scroll"><table class="listing-table"><thead><tr><th>Publicación</th><th>Precio</th><th>Envío</th><th>Total</th><th>Diferencia</th></tr></thead><tbody>${rows}</tbody></table></div>
    </section>`;
  }).join("")}
  <p class="comparison-summary">${escapeHtml(comparison.summary)}</p>`;
}

function historyChart(history, listing) {
  const observations = history
    .filter((item) => item.listing_id === listing.id && item.validation_status === "verified")
    .sort((left, right) => left.observed_at.localeCompare(right.observed_at));
  if (!observations.length) {
    return `<div class="chart-empty">No hay observaciones verificadas para graficar. Los precios pendientes no se presentan como verificados.</div>`;
  }
  const values = observations.map((item) => Number(item.amount_minor));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = max - min || Math.max(max * 0.08, 1);
  const left = 42;
  const right = 690;
  const top = 18;
  const bottom = 158;
  const points = observations.map((item, index) => {
    const x = observations.length === 1 ? (left + right) / 2 : left + index * (right - left) / (observations.length - 1);
    const y = bottom - ((Number(item.amount_minor) - min) / spread) * (bottom - top);
    return { x, y, item };
  });
  const polyline = points.map(({ x, y }) => `${x},${y}`).join(" ");
  const first = observations[0];
  const last = observations.at(-1);
  const dateLabel = (item) => new Intl.DateTimeFormat("es-AR", {
    timeZone: "America/Argentina/Buenos_Aires",
    day: "2-digit",
    month: "short",
  }).format(new Date(item.observed_at));
  return `<div class="chart-wrap"><svg class="history-chart" viewBox="0 0 720 200" role="img" aria-label="Historial verificado de ${escapeAttribute(listing.title || listing.store_name)}">
    <line class="chart-grid" x1="42" y1="18" x2="690" y2="18"></line>
    <line class="chart-grid" x1="42" y1="88" x2="690" y2="88"></line>
    <line class="chart-grid" x1="42" y1="158" x2="690" y2="158"></line>
    <polyline class="chart-line" points="${polyline}"></polyline>
    ${points.map(({ x, y, item }) => `<circle class="chart-point" cx="${x}" cy="${y}" r="4"><title>${escapeHtml(formatMoney(item.amount_minor, item.currency))} · ${escapeHtml(formatDate(item.observed_at))}</title></circle>`).join("")}
    <text class="chart-label" x="42" y="185">${escapeHtml(dateLabel(first))}</text>
    <text class="chart-label" x="690" y="185" text-anchor="end">${escapeHtml(dateLabel(last))}</text>
  </svg></div>`;
}

async function showProductDetail(product) {
  state.selectedProductId = product.id;
  elements.detailPanel.hidden = false;
  elements.detailHeading.textContent = product.name;
  elements.detailSummary.textContent = `${product.canonical_key}${product.brand ? ` · ${product.brand}` : ""}`;
  elements.detailLoading.hidden = false;
  elements.detailContent.innerHTML = "";
  elements.detailPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const [listings, history, comparison] = await Promise.all([
      api.listListings(product.id),
      api.history(product.id),
      api.comparison(product.id),
    ]);
    const latestExecution = state.summaries.get(product.id)?.execution;
    const executionNotice = latestExecution && ["failed", "partial"].includes(latestExecution.status)
      ? `<div class="message">La última actualización terminó ${escapeHtml(statusLabels[latestExecution.status] || latestExecution.status)}. ${escapeHtml(latestExecution.errors.join("; ") || "Revisá la disponibilidad de la integración.")} No se reemplazó la última observación válida; su fecha indica cuándo fue obtenida.</div>`
      : "";
    elements.detailContent.innerHTML = `
      ${executionNotice}
      <section class="detail-section"><h3>Publicaciones y costos</h3>
        ${renderListings(listings, history, comparison)}
      </section>
      <section class="detail-section"><h3>Comparación de ofertas verificadas</h3>
        ${renderComparison(comparison)}
      </section>
      <section class="detail-section"><h3>Historial de precios</h3>
        ${listings.map((listing) => `<div class="detail-section">
          <h3>${escapeHtml(listing.store_name)} · ${escapeHtml(listing.title || listing.url)}</h3>
          ${historyChart(history, listing)}
        </div>`).join("") || `<div class="chart-empty">Agregá una publicación para ver su historial.</div>`}
      </section>`;
  } catch (error) {
    elements.detailContent.innerHTML = `<div class="message">${escapeHtml(userFacingError(error))}</div>`;
  } finally {
    elements.detailLoading.hidden = true;
  }
}

function closeProductDetail() {
  state.selectedProductId = null;
  elements.detailPanel.hidden = true;
  elements.detailContent.innerHTML = "";
}

async function updateProduct(productId, listingId = null, button = null) {
  const priorText = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = "Consultando…";
  }
  try {
    const accepted = listingId
      ? await api.updateListing(listingId)
      : await api.updateProduct(productId);
    const result = await waitForExecution(api, accepted);
    const detail = result.errors.length ? ` ${result.errors.join("; ")}` : "";
    const message = `Ejecución ${result.status === "succeeded" ? "finalizada" : "finalizada con estado " + result.status}.${detail}`;
    showGlobalMessage(message, result.status === "succeeded" ? "success" : "error");
    await loadDashboard();
  } catch (error) {
    showGlobalError(error);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = priorText;
    }
  }
}

function makeCanonicalKey(name) {
  return name.normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase("en")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

function bindEvents() {
  document.querySelector("#refresh-button").addEventListener("click", () => {
    elements.globalMessage.hidden = true;
    loadDashboard();
  });
  elements.search.addEventListener("input", renderProducts);
  document.querySelector("#clear-search").addEventListener("click", () => {
    elements.search.value = "";
    renderProducts();
    elements.search.focus();
  });
  document.querySelector("#close-detail").addEventListener("click", closeProductDetail);
  elements.productMode.addEventListener("change", updateProductFormMode);
  elements.form.elements.name.addEventListener("input", () => {
    if (!elements.form.elements.canonical_key.dataset.edited) {
      elements.form.elements.canonical_key.value = makeCanonicalKey(elements.form.elements.name.value);
    }
  });
  elements.form.elements.canonical_key.addEventListener("input", () => {
    elements.form.elements.canonical_key.dataset.edited = "true";
  });

  elements.form.addEventListener("submit", async (event) => {
    event.preventDefault();
    elements.globalMessage.hidden = true;
    elements.formMessage.hidden = true;
    elements.submitButton.disabled = true;
    elements.submitButton.textContent = "Guardando…";
    const form = new FormData(elements.form);
    try {
      const listing = {
        store_name: form.get("store_name").trim(),
        source_url: form.get("source_url").trim(),
        title: form.get("title").trim() || null,
      };
      if (form.get("product_mode") === "existing") {
        const productId = Number(form.get("existing_product_id"));
        if (!Number.isInteger(productId) || productId <= 0) {
          throw new Error("Seleccioná un producto seguido.");
        }
        await api.createListing(productId, listing);
        elements.form.reset();
        updateProductFormMode();
        showFormMessage("Publicación guardada sin precio observado; la tienda sigue pendiente de integración.");
        await loadDashboard();
        const selected = state.products.find((item) => item.id === productId);
        if (selected) await showProductDetail(selected);
        return;
      }
      const result = await createProductWithListing(api, {
        product: {
          name: form.get("name").trim(),
          canonical_key: form.get("canonical_key").trim(),
        },
        listing,
      });
      elements.form.reset();
      delete elements.form.elements.canonical_key.dataset.edited;
      showFormMessage("Producto y URL guardados. La publicación está pendiente y no tiene un precio observado.");
      await loadDashboard();
      await showProductDetail(state.products.find((item) => item.id === result.product.id));
    } catch (error) {
      const partial = error.createdProduct
        ? ` El producto "${error.createdProduct.name}" sí se creó, pero no se pudo registrar la URL.`
        : "";
      showFormMessage(`${userFacingError(error)}${partial}`, true);
    } finally {
      elements.submitButton.disabled = false;
      elements.submitButton.textContent = "Agregar al seguimiento";
    }
  });

  elements.productsBody.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const productId = Number(button.dataset.productId);
    if (button.dataset.action === "detail") {
      const product = state.products.find((item) => item.id === productId);
      if (product) showProductDetail(product);
    } else if (button.dataset.action === "update-product") {
      updateProduct(productId, null, button);
    } else if (button.dataset.action === "deactivate") {
      state.pendingDeactivateId = productId;
      elements.confirmDialog.hidden = false;
      elements.confirmDeactivate.focus();
    }
  });

  elements.detailContent.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action='update-listing']");
    if (button) updateProduct(state.selectedProductId, Number(button.dataset.listingId), button);
  });
  elements.detailContent.addEventListener("change", (event) => {
    if (event.target.matches("select[name='shipping_status']")) {
      const form = event.target.closest("form");
      const paid = event.target.value === "paid";
      form.querySelectorAll(".shipping-amount-fields").forEach((field) => {
        field.hidden = !paid;
      });
      form.elements.shipping_amount.required = paid;
      form.elements.shipping_currency.required = paid;
    }
  });
  elements.detailContent.addEventListener("submit", async (event) => {
    const form = event.target.closest("form[data-action]");
    if (!form) return;
    event.preventDefault();
    const button = form.querySelector("button[type='submit']");
    button.disabled = true;
    try {
      const values = new FormData(form);
      const productId = Number(form.dataset.productId);
      const listingId = Number(form.dataset.listingId);
      if (form.dataset.action === "manual-observation") {
        const listing = state.summaries.get(productId)?.listings
          .find((item) => item.id === listingId);
        if (!listing) throw new Error("No se encontró la publicación seleccionada.");
        const currency = values.get("currency").trim().toUpperCase();
        await api.createObservation(productId, {
          store_name: listing.store_name,
          store_slug: await storeSlugFromDomain(listing.store_domain),
          store_domain: listing.store_domain,
          source_url: listing.url,
          title: values.get("title").trim(),
          amount_minor: amountToMinorUnits(values.get("amount"), currency),
          currency,
          availability: values.get("availability"),
          extraction_method: "manual",
          validation_status: values.get("verified") === "on" ? "verified" : "pending_review",
        });
        showGlobalMessage(
          values.get("verified") === "on"
            ? "Precio guardado como observado y comprobado manualmente."
            : "Precio guardado pendiente de revisión; todavía no participa de la comparación.",
          "success",
        );
      } else if (form.dataset.action === "manual-shipping") {
        const status = values.get("shipping_status");
        if (status !== "unknown" && !state.summaries.get(productId)?.latest.has(listingId)) {
          throw new Error("Primero registrá un precio observado para indicar la moneda del envío.");
        }
        const quote = {
          status: status === "unknown" ? "unknown" : "known",
          amount_minor: status === "unknown"
            ? null
            : status === "free"
              ? 0
              : amountToMinorUnits(
                values.get("shipping_amount"),
                values.get("shipping_currency"),
                { allowZero: true },
              ),
          currency: status === "unknown" ? null : values.get("shipping_currency").trim().toUpperCase(),
          source: values.get("shipping_source").trim(),
        };
        await api.createShippingQuote(listingId, quote);
        showGlobalMessage("Costo de envío guardado.", "success");
      }
      await loadDashboard();
    } catch (error) {
      showGlobalError(error);
    } finally {
      button.disabled = false;
    }
  });

  document.querySelector("#cancel-deactivate").addEventListener("click", () => {
    state.pendingDeactivateId = null;
    elements.confirmDialog.hidden = true;
  });
  elements.confirmDeactivate.addEventListener("click", async () => {
    const productId = state.pendingDeactivateId;
    if (!productId) return;
    elements.confirmDeactivate.disabled = true;
    try {
      await api.deactivateProduct(productId);
      if (state.selectedProductId === productId) closeProductDetail();
      elements.confirmDialog.hidden = true;
      state.pendingDeactivateId = null;
      await loadDashboard();
    } catch (error) {
      elements.confirmDialog.hidden = true;
      showGlobalError(error);
    } finally {
      elements.confirmDeactivate.disabled = false;
    }
  });
}

bindEvents();
updateProductFormMode();
loadDashboard();
