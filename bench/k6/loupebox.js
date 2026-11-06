// Load scenarios for Loupebox. Pick one with -e SCENARIO=<name>; bench/run.sh wraps this.
//
//   ingest_many  public POST /feedback spread over all sites (the usual case)
//   ingest_hot   the same, all into the biggest site (it takes a row lock per site)
//   list         opening a site's feedback page: list + counts + issue types + tags, as the admin UI does
//   filters      the list with a filter chosen at random
//   search       the list with a search term of known frequency
//   dashboard    GET /dashboard
//   stats        GET /sites/{id}/stats
//   mixed        steady ingest while people browse (list, search, dashboard)
//
// Load shape for the single-endpoint scenarios: the request rate starts at START per second and rises by
// STEP every STEP_SECONDS, STEPS times. Defaults suit a quick check; see bench/README.md for real runs.
// Sites are picked with the same skew as the seeded data (site 1 busiest), except ingest_hot.
import http from "k6/http";
import { check } from "k6";

const BASE = (__ENV.BASE_URL || "http://127.0.0.1:18000") + "/v1/api";
const data = JSON.parse(open("../out/sites.json"));
const sites = data.sites;
const SCENARIO = __ENV.SCENARIO || "list";
const num = (name, fallback) => Number(__ENV[name] || fallback);

const cumulative = [];
sites.reduce((sum, _, i) => {
  cumulative.push(sum + 1 / (i + 1));
  return sum + 1 / (i + 1);
}, 0);
const pickSite = () => {
  const r = Math.random() * cumulative[cumulative.length - 1];
  return sites[cumulative.findIndex((c) => c >= r)];
};
const pick = (list) => list[Math.floor(Math.random() * list.length)];

const stages = () =>
  Array.from({ length: num("STEPS", 6) }, (_, i) => ({
    target: num("START", 10) + num("STEP", 10) * i,
    duration: `${num("STEP_SECONDS", 30)}s`,
  }));
const ramp = (exec) => ({
  executor: "ramping-arrival-rate",
  exec,
  startRate: num("START", 10),
  timeUnit: "1s",
  stages: stages(),
  preAllocatedVUs: num("VUS", 50),
  maxVUs: num("MAX_VUS", 500),
});
const steady = (exec, rate) => ({
  executor: "constant-arrival-rate",
  exec,
  rate,
  timeUnit: "1s",
  duration: `${num("DURATION", 120)}s`,
  preAllocatedVUs: num("VUS", 50),
  maxVUs: num("MAX_VUS", 500),
});

const SCENARIOS = {
  ingest_many: { scenarios: { run: ramp("ingestMany") }, names: ["ingest"] },
  ingest_hot: { scenarios: { run: ramp("ingestHot") }, names: ["ingest"] },
  list: { scenarios: { run: ramp("listPage") }, names: ["list", "counts", "issue_types", "tags"] },
  filters: { scenarios: { run: ramp("filters") }, names: ["filters"] },
  search: { scenarios: { run: ramp("search") }, names: ["search"] },
  dashboard: { scenarios: { run: ramp("dashboard") }, names: ["dashboard"] },
  stats: { scenarios: { run: ramp("stats") }, names: ["stats"] },
  mixed: {
    scenarios: {
      ingest: steady("ingestMany", num("MIX_INGEST", 20)),
      pages: steady("listPage", num("MIX_PAGES", 5)),
      search: steady("search", num("MIX_SEARCH", 2)),
      dashboard: steady("dashboard", num("MIX_DASHBOARD", 1)),
    },
    names: ["ingest", "list", "counts", "issue_types", "tags", "search", "dashboard"],
  },
};
if (!SCENARIOS[SCENARIO]) throw new Error(`Unknown SCENARIO ${SCENARIO}. Choose one of: ${Object.keys(SCENARIOS)}`);

// A threshold on a tagged metric makes k6 print that endpoint on its own line in the summary.
export const options = {
  scenarios: SCENARIOS[SCENARIO].scenarios,
  thresholds: Object.fromEntries([
    ["http_req_failed", ["rate<0.01"]],
    ...SCENARIOS[SCENARIO].names.map((name) => [`http_req_duration{name:${name}}`, ["max>=0"]]),
  ]),
  summaryTrendStats: ["avg", "med", "p(90)", "p(95)", "p(99)", "max"],
};

export function setup() {
  const res = http.post(`${BASE}/auth/login`, JSON.stringify(data.login), {
    headers: { "content-type": "application/json" },
  });
  if (res.status !== 200) throw new Error(`Login failed: ${res.status} ${res.body}`);
  return { auth: { authorization: `Bearer ${res.json("access_token")}` } };
}

const read = (auth, path, name) => {
  const res = http.get(`${BASE}${path}`, { headers: auth, tags: { name } });
  check(res, { [`${name} 200`]: (r) => r.status === 200 });
  return res;
};

const ingest = (site) => {
  const unique = `${__VU}-${__ITER}-${Date.now()}`; // keeps the duplicate check from answering for us
  const res = http.post(
    `${BASE}/feedback`,
    JSON.stringify({ message: `bench ${unique} the checkout page is slow and the button is confusing` }),
    {
      headers: { "content-type": "application/json", "x-api-key": site.key, origin: site.origin },
      tags: { name: "ingest" },
    },
  );
  check(res, { "ingest 201": (r) => r.status === 201 });
};
export const ingestMany = () => ingest(pick(sites));
export const ingestHot = () => ingest(sites[0]);

export function listPage({ auth }) {
  const base = `/sites/${pickSite().id}/feedback`;
  read(auth, `${base}?limit=25`, "list");
  read(auth, `${base}/counts`, "counts");
  read(auth, `${base}/issue-types`, "issue_types");
  read(auth, `${base}/tags`, "tags");
}

const FILTERS = [
  "?status=read",
  "?status=archived",
  "?issue_type=bug",
  "?rating=5",
  "?has_email=true",
  "?assignee=none",
  "?tag=tag03",
  "?created_from=2026-10-01&created_to=2026-10-31",
  "?offset=1000",
];
export function filters({ auth }) {
  read(auth, `/sites/${pickSite().id}/feedback${pick(FILTERS)}`, "filters");
}

const TERMS = ["checkout", "invoice", "zyxwvu"]; // about 5%, 0.5% and 0.01% of rows
export function search({ auth }) {
  read(auth, `/sites/${pickSite().id}/feedback?q=${pick(TERMS)}`, "search");
}

export function dashboard({ auth }) {
  read(auth, "/dashboard", "dashboard");
}

export function stats({ auth }) {
  read(auth, `/sites/${pickSite().id}/stats`, "stats");
}
