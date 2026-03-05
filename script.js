const unique = (items) => [...new Set(items)];

const allBanques = unique(concoursAppearances.map((item) => item.banque)).sort();
const allYears = unique(concoursAppearances.map((item) => item.year)).sort((a, b) => a - b);
const allSubjects = unique(concoursAppearances.map((item) => item.subject)).sort();
const allTypes = unique(
  concoursAppearances.flatMap((item) => (Array.isArray(item.types) && item.types.length ? item.types : ["Non précisé"]))
).sort();

const state = {
  banques: new Set(allBanques),
  years: new Set(allYears),
  subject: allSubjects.includes("Maths") ? "Maths" : allSubjects[0],
  types: new Set(allTypes),
  query: ""
};

const els = {
  banqueFilters: document.getElementById("banqueFilters"),
  yearFilters: document.getElementById("yearFilters"),
  subjectFilters: document.getElementById("subjectFilters"),
  typeFilters: document.getElementById("typeFilters"),
  selectAllBanques: document.getElementById("selectAllBanques"),
  selectAllYears: document.getElementById("selectAllYears"),
  clearYears: document.getElementById("clearYears"),
  selectAllTypes: document.getElementById("selectAllTypes"),
  searchTheme: document.getElementById("searchTheme"),
  resultsBody: document.getElementById("resultsBody"),
  stats: document.getElementById("stats")
};

function escapeHtml(value) {
  const raw = String(value ?? "");
  return raw
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function buildFilterChips(container, values, stateSet, className, onChange) {
  container.innerHTML = values
    .map(
      (value) => `
        <label class="${className}">
          <input type="checkbox" value="${escapeHtml(value)}" ${stateSet.has(value) ? "checked" : ""} />
          <span>${escapeHtml(value)}</span>
        </label>
      `
    )
    .join("");

  container.querySelectorAll("input[type='checkbox']").forEach((input) => {
    input.addEventListener("change", (event) => {
      const { checked, value } = event.target;
      if (checked) {
        stateSet.add(value);
      } else {
        stateSet.delete(value);
      }
      onChange();
    });
  });
}

function buildSubjectChoices() {
  els.subjectFilters.innerHTML = allSubjects
    .map(
      (subject) => `
        <label class="filter-chip">
          <input type="radio" name="subjectChoice" value="${escapeHtml(subject)}" ${state.subject === subject ? "checked" : ""} />
          <span>${escapeHtml(subject)}</span>
        </label>
      `
    )
    .join("");

  els.subjectFilters.querySelectorAll("input[type='radio']").forEach((input) => {
    input.addEventListener("change", (event) => {
      state.subject = event.target.value;
      render();
    });
  });
}

function buildYearChips() {
  els.yearFilters.innerHTML = allYears
    .map(
      (year) => `
        <label class="year-chip">
          <input type="checkbox" value="${year}" ${state.years.has(year) ? "checked" : ""} />
          <span>${year}</span>
        </label>
      `
    )
    .join("");

  els.yearFilters.querySelectorAll("input[type='checkbox']").forEach((input) => {
    input.addEventListener("change", (event) => {
      const year = Number(event.target.value);
      if (event.target.checked) {
        state.years.add(year);
      } else {
        state.years.delete(year);
      }
      render();
    });
  });
}

function getTypes(item) {
  return Array.isArray(item.types) && item.types.length ? item.types : ["Non précisé"];
}

function aggregateResults() {
  const filtered = concoursAppearances.filter((item) => {
    const inBanque = state.banques.has(item.banque);
    const inYear = state.years.has(item.year);
    const inSubject = item.subject === state.subject;
    const inType = getTypes(item).some((type) => state.types.has(type));
    const inQuery = !state.query || item.theme.toLowerCase().includes(state.query);
    return inBanque && inYear && inSubject && inType && inQuery;
  });

  const grouped = new Map();

  filtered.forEach((item) => {
    const key = `${item.subject}||${item.theme}`;
    if (!grouped.has(key)) {
      grouped.set(key, {
        theme: item.theme,
        subject: item.subject,
        count: 0,
        years: new Set(),
        banques: new Map(),
        types: new Map(),
        appearances: []
      });
    }

    const row = grouped.get(key);
    row.count += 1;
    row.years.add(item.year);
    row.banques.set(item.banque, (row.banques.get(item.banque) || 0) + 1);
    getTypes(item).forEach((type) => {
      row.types.set(type, (row.types.get(type) || 0) + 1);
    });
    row.appearances.push(item);
  });

  const aggregated = [...grouped.values()].map((row) => ({
    ...row,
    years: [...row.years].sort((a, b) => a - b),
    banques: [...row.banques.entries()].sort((a, b) => b[1] - a[1]),
    types: [...row.types.entries()].sort((a, b) => b[1] - a[1]),
    appearances: row.appearances.sort((a, b) => b.year - a.year)
  }));

  aggregated.sort((a, b) => {
    if (b.count !== a.count) {
      return b.count - a.count;
    }
    if (b.years.length !== a.years.length) {
      return b.years.length - a.years.length;
    }
    return a.theme.localeCompare(b.theme);
  });

  return { filtered, aggregated };
}

function renderStats(filtered, aggregated) {
  const top = aggregated[0];
  const yearRange = state.years.size
    ? `${Math.min(...state.years)}-${Math.max(...state.years)}`
    : "Aucune annee";

  els.stats.innerHTML = `
    <article class="stat-card">
      <div class="stat-label">Occurrences prises en compte</div>
      <div class="stat-value">${filtered.length}</div>
    </article>
    <article class="stat-card">
      <div class="stat-label">Themes frequents identifies</div>
      <div class="stat-value">${aggregated.length}</div>
    </article>
    <article class="stat-card">
      <div class="stat-label">Top theme (${yearRange})</div>
      <div class="stat-value">${top ? top.count : 0}</div>
      <div>${top ? escapeHtml(top.theme) : "Aucun resultat"}</div>
    </article>
  `;
}

function renderRows(aggregated) {
  if (!aggregated.length) {
    els.resultsBody.innerHTML = `
      <tr>
        <td colspan="8" class="empty">Aucune occurrence avec les filtres actuels.</td>
      </tr>
    `;
    return;
  }

  els.resultsBody.innerHTML = aggregated
    .map((item, index) => {
      const banqueBadges = item.banques
        .map(([banque, count]) => `<span class="badge">${escapeHtml(banque)} x${count}</span>`)
        .join("");

      const yearBadges = item.years
        .map((year) => `<span class="badge">${year}</span>`)
        .join("");

      const typeBadges = item.types
        .map(([type, count]) => `<span class="badge">${escapeHtml(type)} x${count}</span>`)
        .join("");

      const whereItems = item.appearances
        .map((app) => {
          const sourceRef = app.sourceUrl
            ? `<a href="${escapeHtml(app.sourceUrl)}" target="_blank" rel="noreferrer">${escapeHtml(app.section)}</a>`
            : escapeHtml(app.section);
          const typeLabel = getTypes(app).join(", ");
          return `<li>${app.year} - ${escapeHtml(app.banque)} - ${escapeHtml(app.exam)} - ${escapeHtml(typeLabel)} (${sourceRef})</li>`;
        })
        .join("");

      return `
        <tr>
          <td class="rank">${index + 1}</td>
          <td>${escapeHtml(item.theme)}</td>
          <td>${escapeHtml(item.subject)}</td>
          <td><span class="count-pill">${item.count}</span></td>
          <td><div class="badge-row">${banqueBadges}</div></td>
          <td><div class="badge-row">${yearBadges}</div></td>
          <td><div class="badge-row">${typeBadges}</div></td>
          <td>
            <details>
              <summary>Voir ${item.count} occurrence${item.count > 1 ? "s" : ""}</summary>
              <ul>${whereItems}</ul>
            </details>
          </td>
        </tr>
      `;
    })
    .join("");
}

function render() {
  const { filtered, aggregated } = aggregateResults();
  renderStats(filtered, aggregated);
  renderRows(aggregated);
}

function bindEvents() {
  els.selectAllBanques.addEventListener("click", () => {
    state.banques = new Set(allBanques);
    buildFilterChips(els.banqueFilters, allBanques, state.banques, "filter-chip", render);
    render();
  });

  els.selectAllYears.addEventListener("click", () => {
    state.years = new Set(allYears);
    buildYearChips();
    render();
  });

  els.clearYears.addEventListener("click", () => {
    state.years = new Set();
    buildYearChips();
    render();
  });

  els.selectAllTypes.addEventListener("click", () => {
    state.types = new Set(allTypes);
    buildFilterChips(els.typeFilters, allTypes, state.types, "filter-chip", render);
    render();
  });

  els.searchTheme.addEventListener("input", (event) => {
    state.query = event.target.value.trim().toLowerCase();
    render();
  });
}

function init() {
  buildFilterChips(els.banqueFilters, allBanques, state.banques, "filter-chip", render);
  buildYearChips();
  buildSubjectChoices();
  buildFilterChips(els.typeFilters, allTypes, state.types, "filter-chip", render);
  bindEvents();
  render();
}

init();
