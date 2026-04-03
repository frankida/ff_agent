# ESPN Draft Room — React State Reverse-Engineering Guide

This guide walks through discovering the exact React fiber paths needed to
extract live draft state from ESPN's draft room. You need to do this once on a
real (or mock) ESPN draft page, then update `extension/injected.js` with the
discovered paths.

---

## Prerequisites

- A Chrome profile with the Fantasy Agent extension loaded in developer mode
  (`chrome://extensions` → **Load unpacked** → select the `extension/` folder)
- An ESPN Fantasy Football account with at least one league that allows mock
  drafts (Settings → Mock Draft)
- Chrome DevTools open on the ESPN draft tab

---

## Step 1 — Open the ESPN Draft Room

1. Navigate to `https://fantasy.espn.com/football/draft` and start or join a
   mock draft.
2. Once the draft room UI is visible, open DevTools: `Cmd+Option+I` (macOS) /
   `Ctrl+Shift+I` (Windows/Linux).
3. Switch to the **Console** tab.

---

## Step 2 — Find the React Root Element

Paste this snippet into the Console and press Enter:

```js
// Find every DOM node that has a React fiber key attached
const fiberKey = el =>
  Object.keys(el).find(k =>
    k.startsWith('__reactFiber$') ||
    k.startsWith('__reactInternalInstance$')
  );

const roots = [...document.querySelectorAll('*')].filter(fiberKey);
console.log('React-managed nodes:', roots.length);
console.log('First few:', roots.slice(0, 5));
```

Note the selector of the **outermost** React-managed node — this is the root
ESPN uses. Typical candidates:

| Selector | Likelihood |
|---|---|
| `#app` | High |
| `#root` | High |
| `[data-reactroot]` | Medium |
| `#fitt-analytics-root` | Medium |

Update the `candidates` array at the top of `injected.js`'s `findReactRoot()`
function with the correct selector.

---

## Step 3 — Traverse the Fiber Tree to Find Draft State

Once you know the root element (e.g. `document.getElementById('app')`):

```js
// Helper: walk every fiber node and collect component display names
function walkFiber(fiber, depth = 0, maxDepth = 80, results = []) {
  if (!fiber || depth > maxDepth) return results;
  const name =
    (fiber.type && (fiber.type.displayName || fiber.type.name)) || '(anonymous)';
  results.push({ depth, name, fiber });
  walkFiber(fiber.child,   depth + 1, maxDepth, results);
  walkFiber(fiber.sibling, depth,     maxDepth, results);
  return results;
}

const rootEl  = document.getElementById('app'); // adjust selector
const fiberKey = Object.keys(rootEl).find(k => k.startsWith('__reactFiber$'));
const rootFiber = rootEl[fiberKey];

const allNodes = walkFiber(rootFiber);
console.table(allNodes.map(n => ({ depth: n.depth, name: n.name })));
```

Look for component names such as:
- `DraftRoom`, `DraftBoard`, `DraftApp`
- `DraftProvider`, `DraftContext`, `DraftStore`
- Any component with "Draft" or "Pick" in the name

---

## Step 4 — Inspect a Promising Component's State

Once you spot a candidate (say `DraftRoom` at index 42 in the table above):

```js
const node = allNodes[42]; // replace with actual index
const fiber = node.fiber;

console.log('memoizedProps:', fiber.memoizedProps);
console.log('memoizedState:', fiber.memoizedState);
console.log('stateNode:', fiber.stateNode);
```

Drill into whichever object contains arrays or objects with keys like:

| Key to look for | Likely meaning |
|---|---|
| `picks` / `draftPicks` | Array of completed picks |
| `currentPick` / `pickOnClock` | The pick currently being made |
| `teams` / `draftTeams` | Participating teams |
| `myTeamId` / `primaryTeamId` | The authenticated user's team |
| `inProgress` / `draftInProgress` | Boolean: draft is running |
| `round` / `currentRound` | Current round number |

---

## Step 5 — Confirm the Path Survives a Re-render

After a pick is made the fiber tree may update. Re-run your traversal after a
pick lands and confirm the same path still works:

```js
// Quick re-check after a pick
const fiberNow = rootEl[Object.keys(rootEl).find(k => k.startsWith('__reactFiber$'))];
const stateNow = fiberNow
  /* TODO: insert the discovered chain here, e.g.: */
  /* .child.child.memoizedProps.draftData */;
console.log('picks after pick:', stateNow && stateNow.picks);
```

---

## Step 6 — Update `injected.js`

Once you have a reliable path, open `extension/injected.js` and:

1. **Update `findReactRoot()`** — ensure the correct root selector is first in
   the `candidates` array.

2. **Replace the traversal TODO in `extractDraftState()`** — change the
   `traverseFiber` visitor to match on the component name or prop shape you
   discovered:

   ```js
   // Example — replace with real component name / prop keys
   const name = fiber.type && (fiber.type.displayName || fiber.type.name);
   if (name === 'DraftRoom') {
     draftStateNode = fiber.memoizedProps.draftData; // use discovered path
     return true;
   }
   ```

3. **Map the raw state in Step 3 of `extractDraftState()`**:

   ```js
   result.picks       = draftStateNode.picks       || [];
   result.currentPick = draftStateNode.currentPick || null;
   result.teams       = draftStateNode.teams        || null;
   result.myTeamId    = draftStateNode.myTeamId     || null;
   result.inProgress  = Boolean(draftStateNode.inProgress);
   result.raw         = draftStateNode;
   ```

4. Reload the extension (`chrome://extensions` → refresh icon) and open the
   draft room again. The Console should show pick data being dispatched every
   3 seconds.

---

## Step 7 — Verify End-to-End

With the Python server running (`fantasy-agent serve` or `uvicorn ...`):

1. Confirm the Console shows `[fantasy-agent:injected] Draft state extracted`.
2. Confirm `[fantasy-agent:content] Received fantasy-agent-picks event`.
3. Confirm `[fantasy-agent:background] Picks forwarded successfully`.
4. Check the server logs for incoming POST requests to `/picks`.

---

## Useful DevTools Helpers

```js
// Pretty-print any object, collapsing nested arrays
const pp = o => JSON.stringify(o, null, 2);

// Find a fiber node by component display name
function findFiberByName(root, name) {
  const results = [];
  walkFiber(root, 0, 100, []).forEach(n => {
    if (n.name.toLowerCase().includes(name.toLowerCase())) results.push(n);
  });
  return results;
}

// Usage
findFiberByName(rootFiber, 'draft').forEach(n =>
  console.log(n.depth, n.name, n.fiber.memoizedProps)
);
```

---

## Notes

- ESPN occasionally updates their React component tree between seasons. If the
  extension stops working after a platform update, re-run steps 2–5.
- The fiber key suffix (e.g. `__reactFiber$abc123`) changes each page load but
  the `startsWith` check in `injected.js` handles this automatically.
- React DevTools (browser extension) can also help: select a component in the
  **Components** panel and run `$r.props` / `$r.state` in the Console to
  inspect the currently-selected component's state.
