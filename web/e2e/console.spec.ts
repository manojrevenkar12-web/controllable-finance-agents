import AxeBuilder from "@axe-core/playwright";
import { type Page, type Route, expect, test } from "@playwright/test";
import documents from "./fixtures/documents.json" with { type: "json" };
import people from "./fixtures/people.json" with { type: "json" };
import proposals from "./fixtures/proposals.json" with { type: "json" };
import quality from "./fixtures/quality.json" with { type: "json" };
import reference from "./fixtures/reference.json" with { type: "json" };
import session from "./fixtures/session.json" with { type: "json" };

type Handler = (route: Route) => Promise<void>;

async function mockApi(page: Page, overrides: Record<string, Handler> = {}) {
  const decisions: { id: string; body: unknown }[] = [];
  let open = [...proposals];
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    for (const [prefix, h] of Object.entries(overrides)) if (url.pathname.startsWith(prefix)) return h(route);
    const p = url.pathname;
    if (p === "/api/dev/people") return route.fulfill({ json: people });
    if (p === "/api/dev/sign-in") return route.fulfill({ json: session });
    if (p === "/api/reference") return route.fulfill({ json: reference });
    if (p === "/api/documents") return route.fulfill({ json: documents });
    if (p === "/api/proposals") return route.fulfill({ json: open });
    if (p === "/api/quality") return route.fulfill({ json: quality });
    if (p.startsWith("/api/journal")) return route.fulfill({ json: [] });
    const m = p.match(/^\/api\/proposals\/([^/]+)\/decision$/);
    if (m) {
      decisions.push({ id: m[1], body: route.request().postDataJSON() });
      open = open.filter((x) => x.id !== m[1]);
      return route.fulfill({ json: { id: m[1], status: "approved" } });
    }
    return route.fulfill({ status: 404, json: { title: "No such endpoint" } });
  });
  return decisions;
}

async function signIn(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "To approve" })).toBeVisible();
}

async function accessible(page: Page) {
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
}

const ready = proposals.filter((p) => p.kind === "coding" && p.evidence[0]?.bucket === "ready");

test("sign-in page is accessible", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await expect(page.getByLabel("Person")).toBeVisible();
  await accessible(page);
});

test("an accountant approves one booking and the queue updates", async ({ page }) => {
  const decisions = await mockApi(page);
  await signIn(page);
  await expect(page.getByRole("button", { name: `Ready to approve · ${ready.length}` })).toBeVisible();
  await accessible(page);
  await page.getByRole("button", { name: "Approve booking" }).first().click();
  await expect(page.getByRole("button", { name: `Ready to approve · ${ready.length - 1}` })).toBeVisible();
  expect(decisions[0]).toEqual({ id: ready[0].id, body: { decision: "approve" } });
});

test("bulk approval approves every ready booking", async ({ page }) => {
  const decisions = await mockApi(page);
  await signIn(page);
  await page.getByRole("button", { name: `Approve all ${ready.length}` }).click();
  await expect(page.getByText(/Nothing in “Ready to approve”/)).toBeVisible();
  expect(decisions.map((d) => d.id).sort()).toEqual(ready.map((p) => p.id).sort());
});

test("changing a booking sends an override with the corrected account", async ({ page }) => {
  const decisions = await mockApi(page);
  await signIn(page);
  await page.getByRole("button", { name: /Needs a look/ }).click();
  await page.getByRole("button", { name: "Change" }).first().click();
  await page.getByLabel("Account for line 1").first().selectOption("6815");
  await page.getByRole("button", { name: "Save booking" }).click();
  await expect.poll(() => decisions.length).toBe(1);
  const body = decisions[0].body as { decision: string; payload: { lines: { account: string }[] } };
  expect(body.decision).toBe("override");
  expect(body.payload.lines[0].account).toBe("6815");
});

test("payment checks can hold a payment", async ({ page }) => {
  const decisions = await mockApi(page);
  await signIn(page);
  await page.getByRole("button", { name: /Before payment/ }).click();
  await accessible(page);
  await page.getByRole("button", { name: "Hold payment" }).first().click();
  await expect.poll(() => decisions.length).toBe(1);
  expect((decisions[0].body as { decision: string }).decision).toBe("approve");
});

test("close entries show their arithmetic", async ({ page }) => {
  await mockApi(page);
  await signIn(page);
  await page.getByRole("link", { name: "Close" }).click();
  await expect(page.getByRole("heading", { name: "Close", exact: true })).toBeVisible();
  await expect(page.getByText(/days fall after/).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Download DATEV export" })).toBeVisible();
  await accessible(page);
});

test("agent quality shows the release decisions", async ({ page }) => {
  await mockApi(page);
  await signIn(page);
  await page.getByRole("link", { name: "Agent quality" }).click();
  await expect(page.getByRole("heading", { name: "Release decisions" })).toBeVisible();
  await expect(page.getByText("Does not ship").first()).toBeVisible();
  await accessible(page);
});

test("a failed load explains itself and retries", async ({ page }) => {
  let calls = 0;
  await mockApi(page, {
    "/api/proposals": async (route) => {
      calls += 1;
      if (calls <= 2)
        return route.fulfill({
          status: 503,
          json: { title: "Ledger unavailable", detail: "database restarting" },
        });
      return route.fulfill({ json: proposals });
    },
  });
  await signIn(page).catch(() => undefined);
  await expect(page.getByRole("alert")).toContainText("Could not load the proposals");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("button", { name: /Ready to approve/ })).toBeVisible();
});

test("an empty queue says what comes next", async ({ page }) => {
  await mockApi(page, { "/api/proposals": (route) => route.fulfill({ json: [] }) });
  await page.goto("/");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("All caught up.")).toBeVisible();
  await page.getByRole("link", { name: "Close" }).click();
  await expect(page.getByText("No month-end entries to decide.")).toBeVisible();
});

test("a skeleton shows while proposals load", async ({ page }) => {
  await mockApi(page, {
    "/api/proposals": async (route) => {
      await new Promise((r) => setTimeout(r, 800));
      await route.fulfill({ json: proposals });
    },
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByLabel("Loading proposals")).toBeVisible();
  await expect(page.getByRole("button", { name: /Ready to approve/ })).toBeVisible();
});

test("works on a phone without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page);
  await signIn(page);
  for (const hash of ["#/inbox", "#/close", "#/quality"]) {
    await page.goto(`/${hash}`);
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, hash).toBeLessThanOrEqual(0);
  }
});
