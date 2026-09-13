/* Turn a sheet tab (header + rows) into a dashboard: KPI cards, a chart, and a
   filterable, color-coded table. Data is read from a <script type="application/json">
   element with id "sheet-data": { tab, rows: [[...]] }. Chart.js optional. */
(function () {
  "use strict";

  var el = document.getElementById("sheet-data");
  if (!el) return;
  var payload = JSON.parse(el.textContent || "{}");
  var raw = payload.rows || [];
  if (!raw.length) return;

  // --- find the header row: the row (in the first ~16) with the most TEXT
  //     (non-numeric) labels that is followed by a data row containing numbers.
  //     Headers are mostly words; data rows are mostly numbers — so scoring by
  //     text cells avoids picking a numeric total row (or a title/legend block)
  //     as the header. ---
  function nonEmpty(r) { return r.filter(function (c) { return c !== null && c !== ""; }).length; }
  function isNumericCell(c) {
    if (c === null || c === "") return false;
    if (typeof c === "number") return isFinite(c);
    var s = String(c).replace(/,/g, "").trim();
    if (s === "") return false;
    var n = Number(s);              // strict: the WHOLE cell must be a number
    return !isNaN(n) && isFinite(n);
  }
  function textCount(r) {
    return r.filter(function (c) { return c !== null && c !== "" && !isNumericCell(c); }).length;
  }
  function looksNumericRow(r) { return r && r.some(isNumericCell); }
  var headerIdx = 0, best = -1;
  for (var i = 0; i < Math.min(16, raw.length); i++) {
    var score = textCount(raw[i]);
    // require ≥2 text labels and a following row that has numbers (real data)
    if (score >= 2 && looksNumericRow(raw[i + 1]) && score > best) {
      best = score; headerIdx = i;
    }
  }
  if (best < 0) {  // fallback: richest (most non-empty) of the first 3 rows
    for (var j = 0; j < Math.min(3, raw.length); j++) {
      if (nonEmpty(raw[j]) > best) { best = nonEmpty(raw[j]); headerIdx = j; }
    }
  }
  var headers = raw[headerIdx].map(function (h, i) {
    h = (h === null || h === "") ? "" : String(h);
    return h || ("Col " + (i + 1));
  });
  var body = raw.slice(headerIdx + 1);

  // Excel error literals carried in from broken formulas/external links
  var EXCEL_ERR = /^#(ref|n\/a|value|div\/0|name|null|num|error|calc|spill|getting_data)\b!?\??$/i;
  function isErr(v) {
    return v !== null && v !== undefined && EXCEL_ERR.test(String(v).trim());
  }

  // --- parse a cell as number (strip commas) ---
  function num(v) {
    if (isErr(v)) return null;
    if (v === null || v === "") return null;
    if (typeof v === "number") return isFinite(v) ? v : null;
    var s = String(v).replace(/,/g, "").trim();
    if (s === "") return null;
    var n = Number(s);              // strict: "203D10..." -> NaN (not 203)
    return (isNaN(n) || !isFinite(n)) ? null : n;
  }
  // column types
  var isNum = headers.map(function (_, c) {
    var t = 0, ok = 0;
    for (var r = 0; r < body.length; r++) {
      var v = body[r][c];
      if (v === null || v === "") continue;
      t++; if (num(v) !== null) ok++;
    }
    return t > 0 && ok / t >= 0.6;
  });
  var isPct = headers.map(function (h) { return /%/.test(h); });
  // identifier-like columns (invoice/voucher/code/hsn/…) — never summed/charted
  var isId = headers.map(function (h, c) {
    return isNum[c] && /(^|[^a-z])(no|number|code|id|invoice|voucher|hsn|sac|gstin|tin|pin ?code|ref|reference|serial|sr)([^a-z]|$)/i.test(h);
  });
  // rate-like columns (per-unit) shouldn't be summed — averaged instead
  var isRate = headers.map(function (h, c) {
    return isNum[c] && !isPct[c] && !isId[c] && /\b(asp|rate|cost|price|per\b)/i.test(h) && !/value|amount|total consumption/i.test(h);
  });
  var textCols = headers.map(function (_, c) { return c; }).filter(function (c) { return !isNum[c]; });
  var numCols = headers.map(function (_, c) { return c; }).filter(function (c) { return isNum[c]; });

  // Pivots use an outline layout: the group label is shown only on the first
  // row of each group and left blank below. Forward-fill the leading label
  // columns (the text columns before the first value column) so every row
  // shows its group.
  var firstNum = isNum.indexOf(true);
  var labelEnd = firstNum < 0 ? headers.length : firstNum;
  for (var lc = 0; lc < labelEnd; lc++) {
    if (isNum[lc]) continue;
    var last = "";
    for (var rr = 0; rr < body.length; rr++) {
      var cell = body[rr][lc];
      if (cell === null || cell === "") body[rr][lc] = last;
      else last = cell;
    }
  }
  // KPI columns: additive first (summed), then rate/pct (averaged); never ids
  var addCols = numCols.filter(function (c) { return !isPct[c] && !isRate[c] && !isId[c]; });
  var avgCols = numCols.filter(function (c) { return (isPct[c] || isRate[c]) && !isId[c]; });
  var kpiCols = addCols.concat(avgCols).slice(0, 4);
  var chartMetric = addCols.length ? addCols[0] : null;

  function isTotalRow(row) {
    var first = (row[textCols[0]] || row[0] || "").toString().toLowerCase().trim();
    return first === "total" || first === "grand total" || first.indexOf(" total") >= 0;
  }

  // --- formatting ---
  function fmtNum(v) {
    if (v === null) return "";
    var a = Math.abs(v);
    var d = a >= 1000 ? 0 : (a >= 1 ? 2 : 3);
    return v.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function fmtPct(v) {
    if (v === null) return "";
    var p = Math.abs(v) <= 1 ? v * 100 : v;
    return p.toFixed(1) + "%";
  }
  // compact Indian units for KPI headline values
  function fmtCompact(v) {
    if (v === null) return "";
    var a = Math.abs(v), s = v < 0 ? "-" : "";
    if (a >= 1e7) return s + (a / 1e7).toFixed(2) + " Cr";
    if (a >= 1e5) return s + (a / 1e5).toFixed(2) + " L";
    if (a >= 1e3) return s + (a / 1e3).toFixed(1) + " K";
    return fmtNum(v);
  }
  // throughput banding (matches the workbook legend)
  function pctClass(v) {
    var p = Math.abs(v) <= 1 ? v : v / 100;
    if (p <= 0.30) return "cell-red";
    if (p <= 0.40) return "cell-amber";
    if (p <= 0.60) return "cell-blue";
    return "cell-green";
  }

  var catCol = textCols.length ? textCols[0] : 0;
  var filterCol = catCol;

  // interactivity/colour state
  var sortCol = null, sortDir = -1;
  var KPI_COLORS = ["#4f6ef7", "#1faa59", "#e4572e", "#8a5cf6", "#0ea5b7", "#d9a400"];
  // value columns that get in-cell data bars (numeric, not ids, not %)
  var barCols = numCols.filter(function (c) { return !isId[c] && !isPct[c]; });

  // --- build filter bar ---
  var host = document.getElementById("dash");
  host.innerHTML = "";

  var bar = document.createElement("div");
  bar.className = "dash-filters";
  var distinct = [];
  var seen = {};
  body.forEach(function (row) {
    if (isTotalRow(row)) return;
    var v = row[filterCol]; if (v === null || v === "" || isErr(v)) return;
    v = String(v); if (v.toLowerCase() === "total") return;
    if (!seen[v]) { seen[v] = 1; distinct.push(v); }
  });
  distinct.sort();
  var selHtml = '<option value="">All ' + escapeHtml(headers[filterCol]) + '</option>';
  distinct.forEach(function (v) { selHtml += '<option>' + escapeHtml(v) + '</option>'; });
  bar.innerHTML =
    '<label>' + escapeHtml(headers[filterCol]) + '</label>' +
    '<select id="dash-filter">' + selHtml + '</select>' +
    '<input id="dash-search" type="search" placeholder="Search rows…">' +
    '<span id="dash-count" class="dash-count"></span>';
  host.appendChild(bar);

  var kpiWrap = document.createElement("div");
  kpiWrap.className = "kpi-grid";
  host.appendChild(kpiWrap);

  var chartCard = null, chart = null;
  if (chartMetric !== null && distinct.length > 1 && typeof Chart !== "undefined") {
    chartCard = document.createElement("div");
    chartCard.className = "card chart-card";
    chartCard.innerHTML = '<div class="card-header"><h3>' +
      escapeHtml(headers[chartMetric]) + " by " + escapeHtml(headers[catCol]) +
      '</h3></div><div class="chart-scroll"><div class="chart-inner" id="chart-inner">' +
      '<canvas id="dash-chart"></canvas></div></div>';
    host.appendChild(chartCard);
  }

  var tableCard = document.createElement("div");
  tableCard.className = "card";
  tableCard.innerHTML = '<div class="table-scroll"><table class="data-table dash-table"></table></div>';
  host.appendChild(tableCard);
  var table = tableCard.querySelector("table");

  function currentRows() {
    var fv = document.getElementById("dash-filter").value;
    var sv = (document.getElementById("dash-search").value || "").toLowerCase();
    return body.filter(function (row) {
      if (isTotalRow(row)) return false;
      if (fv && String(row[filterCol]) !== fv) return false;
      if (sv) {
        var hit = row.some(function (c) { return c !== null && String(c).toLowerCase().indexOf(sv) >= 0; });
        if (!hit) return false;
      }
      return true;
    });
  }

  function renderKpis(rows) {
    kpiWrap.innerHTML = "";
    kpiCols.forEach(function (c) {
      var vals = rows.map(function (r) { return num(r[c]); }).filter(function (v) { return v !== null; });
      var averaged = isPct[c] || isRate[c];
      var display, val;
      if (averaged) {
        val = vals.length ? vals.reduce(function (a, b) { return a + b; }, 0) / vals.length : 0;
        display = isPct[c] ? fmtPct(val) : fmtCompact(val);
      } else {
        val = vals.reduce(function (a, b) { return a + b; }, 0);
        display = fmtCompact(val);
      }
      var card = document.createElement("div");
      card.className = "card kpi-card";
      var color = KPI_COLORS[kpiWrap.children.length % KPI_COLORS.length];
      card.style.borderLeft = "4px solid " + color;
      card.innerHTML = '<span class="kpi-label">' + (averaged ? "Avg " : "Total ") +
        escapeHtml(headers[c]) + '</span><span class="kpi-value" style="color:' + color +
        '">' + display + '</span>';
      kpiWrap.appendChild(card);
    });
  }

  function renderChart(rows) {
    if (!chartCard) return;
    var metric = chartMetric;
    // Group by the first label column that actually VARIES in the current rows,
    // so filtering to a single Item Group breaks the chart down by the next
    // dimension (e.g. Item/Service Code) instead of showing one big bar.
    var chartCat = catCol;
    for (var ci = 0; ci < textCols.length; ci++) {
      var col = textCols[ci], distinctVals = {}, n = 0;
      for (var ri = 0; ri < rows.length; ri++) {
        var vv = rows[ri][col];
        if (vv === null || vv === "") continue;
        if (!distinctVals[vv]) { distinctVals[vv] = 1; if (++n > 1) break; }
      }
      if (n > 1) { chartCat = col; break; }
    }
    var h3 = chartCard.querySelector(".card-header h3");
    if (h3) h3.textContent = headers[metric] + " by " + headers[chartCat];
    var agg = {};
    rows.forEach(function (r) {
      var k = r[chartCat] === null || r[chartCat] === "" ? "—" : String(r[chartCat]);
      var v = num(r[metric]); if (v === null) return;
      agg[k] = (agg[k] || 0) + v;
    });
    var pairs = Object.keys(agg).map(function (k) { return [k, agg[k]]; });
    pairs.sort(function (a, b) { return Math.abs(b[1]) - Math.abs(a[1]); });
    pairs = pairs.slice(0, 60);  // show many categories; the chart scrolls horizontally
    var labels = pairs.map(function (p) { return p[0]; });
    var data = pairs.map(function (p) { return p[1]; });
    // widen the chart when there are many categories so bars stay readable (scrolls)
    var inner = document.getElementById("chart-inner");
    if (inner) inner.style.minWidth = "max(100%, " + (labels.length * 62) + "px)";
    if (chart) chart.destroy();
    chart = new Chart(document.getElementById("dash-chart"), {
      type: "bar",
      data: { labels: labels, datasets: [{ label: headers[metric], data: data, backgroundColor: "#4f6ef7", borderRadius: 4 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { ticks: { autoSkip: false, maxRotation: 60, minRotation: 30, font: { size: 10 } } },
                  y: { ticks: { callback: function (v) { return fmtNum(v); } } } }
      }
    });
  }

  function renderTable(rows) {
    // per-column magnitude for the in-cell data bars
    var maxAbs = {};
    barCols.forEach(function (c) {
      var m = 0;
      rows.forEach(function (r) { var n = num(r[c]); if (n !== null) { var a = Math.abs(n); if (a > m) m = a; } });
      maxAbs[c] = m;
    });

    var thead = "<thead><tr>";
    headers.forEach(function (h, c) {
      var caret = sortCol === c ? (sortDir < 0 ? " ▼" : " ▲") : "";
      thead += '<th class="sortable ' + (isNum[c] ? "num" : "") + '" data-col="' + c + '">' +
        escapeHtml(h) + '<span class="sort-caret">' + caret + "</span></th>";
    });
    thead += "</tr></thead>";

    var tb = "<tbody>";
    rows.slice(0, 400).forEach(function (row) {
      tb += "<tr>";
      headers.forEach(function (h, c) {
        var v = row[c];
        if (isErr(v)) {
          tb += '<td class="' + (isNum[c] ? "num " : "") + 'cell-err">—</td>';
        } else if (isId[c]) {
          tb += '<td class="num">' + escapeHtml(v == null ? "" : String(v)) + "</td>";
        } else if (isPct[c]) {
          var p = num(v);
          tb += p === null ? "<td class=\"num\"></td>"
            : '<td class="num ' + pctClass(p) + '">' + fmtPct(p) + "</td>";
        } else if (isNum[c]) {
          var n = num(v);
          if (n === null) { tb += '<td class="num">' + escapeHtml(v == null ? "" : String(v)) + "</td>"; }
          else {
            var w = maxAbs[c] > 0 ? Math.round(Math.abs(n) / maxAbs[c] * 100) : 0;
            var barCol = n < 0 ? "rgba(228,87,46,.18)" : "rgba(79,110,247,.18)";
            var cls = "num data-bar" + (n < 0 ? " num-neg" : "");
            tb += '<td class="' + cls + '" style="background:linear-gradient(90deg,' +
              barCol + " " + w + "%, transparent " + w + '%)">' + fmtNum(n) + "</td>";
          }
        } else {
          tb += "<td>" + escapeHtml(v == null ? "" : String(v)) + "</td>";
        }
      });
      tb += "</tr>";
    });
    tb += "</tbody>";
    table.innerHTML = thead + tb;
  }

  function sortRows(rows) {
    if (sortCol === null) return rows;
    var c = sortCol, dir = sortDir;
    return rows.slice().sort(function (a, b) {
      if (isNum[c]) {
        var an = num(a[c]), bn = num(b[c]);
        an = an === null ? -Infinity : an; bn = bn === null ? -Infinity : bn;
        return (an - bn) * dir;
      }
      var av = (a[c] == null ? "" : String(a[c])).toLowerCase();
      var bv = (b[c] == null ? "" : String(b[c])).toLowerCase();
      return av < bv ? -dir : av > bv ? dir : 0;
    });
  }

  // click a header to sort
  table.addEventListener("click", function (e) {
    var th = e.target.closest("th");
    if (!th || th.dataset.col === undefined) return;
    var c = parseInt(th.dataset.col, 10);
    if (sortCol === c) sortDir = -sortDir; else { sortCol = c; sortDir = -1; }
    refresh();
  });

  function refresh() {
    var rows = sortRows(currentRows());
    document.getElementById("dash-count").textContent = rows.length + " rows";
    renderKpis(rows);
    renderChart(rows);
    renderTable(rows);
  }

  document.getElementById("dash-filter").addEventListener("change", refresh);
  document.getElementById("dash-search").addEventListener("input", refresh);
  refresh();

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (m) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m];
    });
  }
})();
