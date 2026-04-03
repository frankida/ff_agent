/**
 * injected.js — Runs in the MAIN world.
 *
 * Because this file is injected via a <script> tag by content.js it has full
 * access to the page's JavaScript globals, including React's fiber internals
 * (window.__reactFiber$*, __reactInternalInstance$*, etc.).
 *
 * HOW IT WORKS
 * ────────────
 * 1. Every POLL_INTERVAL_MS milliseconds we look for a React root element.
 * 2. We traverse the fiber tree looking for draft-related state.
 * 3. We normalise whatever we find into a standard payload and dispatch it
 *    as a CustomEvent so content.js (isolated world) can forward it.
 *
 * TODO ITEMS (require live/mock draft reverse-engineering)
 * ────────────────────────────────────────────────────────
 * Search for "TODO:" in this file to locate every spot that needs a real path
 * once the React component tree has been inspected during a mock draft.
 * See docs/espn_react_reverse_engineering.md for step-by-step instructions.
 */

(function () {
  'use strict';

  const POLL_INTERVAL_MS = 3000; // 3 seconds
  const EVENT_NAME = 'fantasy-agent-picks';
  const LOG_PREFIX = '[fantasy-agent:injected]';

  // ── Utility: find the React fiber key on a DOM node ────────────────────────
  /**
   * Returns the React fiber/instance key name attached to a DOM element, or
   * null if the element has no React fiber.
   *
   * React 16+ attaches internal state to DOM nodes under a randomised key
   * like `__reactFiber$abc123` or the older `__reactInternalInstance$abc123`.
   */
  function getReactFiberKey(element) {
    return (
      Object.keys(element).find(
        (k) =>
          k.startsWith('__reactFiber$') ||
          k.startsWith('__reactInternalInstance$')
      ) || null
    );
  }

  // ── Utility: walk up/down the fiber tree ───────────────────────────────────
  /**
   * Traverses the fiber tree starting at `fiber` (upward via `return`,
   * downward via `child`/`sibling`) and calls `visitor(fiber)` on every node.
   * Stops descent when `visitor` returns true (found what we needed).
   *
   * @param {object} fiber   – Starting fiber node
   * @param {Function} visitor – Called with each fiber; return true to stop
   * @param {number} maxDepth – Safety limit to avoid infinite loops
   */
  function traverseFiber(fiber, visitor, maxDepth) {
    if (!fiber || maxDepth <= 0) return false;
    if (visitor(fiber)) return true;

    // Traverse children
    if (traverseFiber(fiber.child, visitor, maxDepth - 1)) return true;
    // Traverse siblings
    if (traverseFiber(fiber.sibling, visitor, maxDepth - 1)) return true;

    return false;
  }

  // ── Core: find a React root fiber ─────────────────────────────────────────
  /**
   * Attempts to locate a React fiber root from the DOM.
   * Returns the root fiber object or null.
   */
  function findReactRoot() {
    // Strategy A: look for the root container ESPN typically uses
    // TODO: confirm the actual root selector used by ESPN's draft app.
    //       Candidates: '#fitt-analytics-root', '#app', '#root', '[data-reactroot]'
    const candidates = [
      document.getElementById('app'),
      document.getElementById('root'),
      document.querySelector('[data-reactroot]'),
      document.querySelector('#fitt-analytics-root'),
    ].filter(Boolean);

    for (const el of candidates) {
      const key = getReactFiberKey(el);
      if (key) {
        console.log(LOG_PREFIX, 'Found React fiber root on element:', el, 'key:', key);
        return el[key];
      }
    }

    // Strategy B: brute-force scan the body's direct children
    for (const child of document.body.children) {
      const key = getReactFiberKey(child);
      if (key) {
        console.log(LOG_PREFIX, 'Found React fiber root via body scan:', child);
        return child[key];
      }
    }

    return null;
  }

  // ── Core: extract draft state from the fiber tree ─────────────────────────
  /**
   * Walks the fiber tree and attempts to extract ESPN draft state.
   *
   * Returns an object with shape:
   * {
   *   picks:       Array|null,   // array of completed pick objects
   *   currentPick: object|null,  // the pick currently on the clock
   *   teams:       Array|null,   // participating teams
   *   myTeamId:    string|null,  // the user's own team id
   *   inProgress:  boolean,      // whether a draft is actively running
   *   raw:         object|null,  // raw extracted state for debugging
   * }
   *
   * All fields default to null/false when not yet found.
   */
  function extractDraftState(rootFiber) {
    const result = {
      picks: [],
      currentPick: null,
      teams: null,
      myTeamId: null,
      inProgress: false,
      raw: null,
    };

    try {
      // ── TODO: Step 1 – Find the component that holds draft state ───────────
      //
      // During a mock draft, open DevTools and run the snippet from
      // docs/espn_react_reverse_engineering.md to discover which component's
      // `memoizedState` or `memoizedProps` contains the picks array.
      //
      // Common patterns to look for:
      //   fiber.memoizedState.queue.lastRenderedState
      //   fiber.memoizedProps.draftData
      //   fiber.memoizedProps.store.getState().draft
      //   fiber.stateNode.state.draft
      //
      // Once found, replace this comment block with the actual traversal.

      let draftStateNode = null;

      traverseFiber(rootFiber, function (fiber) {
        // ── TODO: Step 2 – Identify the correct fiber node ──────────────────
        //
        // Heuristic: look for a fiber whose memoizedProps or memoizedState
        // contains an object with a `picks` or `draftPicks` key.
        //
        // Example (replace with real path once discovered):
        //   const props = fiber.memoizedProps;
        //   if (props && Array.isArray(props.picks)) {
        //     draftStateNode = props;
        //     return true; // stop traversal
        //   }
        //
        // For Redux-style apps, the state may be on the stateNode:
        //   const state = fiber.stateNode && fiber.stateNode.getState && fiber.stateNode.getState();
        //   if (state && state.draft) {
        //     draftStateNode = state.draft;
        //     return true;
        //   }

        const props = fiber.memoizedProps;
        if (props) {
          // TODO: replace the key names below with actual ESPN prop names
          if (Array.isArray(props.picks) || Array.isArray(props.draftPicks)) {
            draftStateNode = props;
            return true;
          }
        }

        const memoState = fiber.memoizedState;
        if (memoState && memoState.memoizedState) {
          // useState / useReducer hook chain — ESPN may store draft here
          // TODO: walk hook linked list to find the right state slot
        }

        return false;
      }, /* maxDepth= */ 200);

      if (!draftStateNode) {
        // Not yet found — this is expected until TODOs above are resolved
        console.debug(LOG_PREFIX, 'Draft state node not found in fiber tree (expected until reverse-engineered).');
        return result;
      }

      // ── TODO: Step 3 – Map raw state to our normalised schema ─────────────
      //
      // Once draftStateNode is populated, map its fields:
      //
      //   result.picks       = draftStateNode.picks || draftStateNode.draftPicks || [];
      //   result.currentPick = draftStateNode.currentPick || draftStateNode.pickOnClock || null;
      //   result.teams       = draftStateNode.teams || draftStateNode.draftTeams || null;
      //   result.myTeamId    = draftStateNode.myTeamId || draftStateNode.primaryTeamId || null;
      //   result.inProgress  = draftStateNode.inProgress || draftStateNode.draftInProgress || false;
      //   result.raw         = draftStateNode; // include for debugging

      result.raw = draftStateNode;
      console.log(LOG_PREFIX, 'Draft state extracted (raw):', draftStateNode);

    } catch (err) {
      console.error(LOG_PREFIX, 'Error traversing React fiber tree:', err);
    }

    return result;
  }

  // ── Poll loop ──────────────────────────────────────────────────────────────
  function poll() {
    try {
      const rootFiber = findReactRoot();

      if (!rootFiber) {
        console.debug(LOG_PREFIX, 'React fiber root not found yet — will retry.');
        dispatchPicksEvent({
          picks: [],
          currentPick: null,
          teams: null,
          myTeamId: null,
          inProgress: false,
          raw: null,
        });
        return;
      }

      const draftState = extractDraftState(rootFiber);
      dispatchPicksEvent(draftState);

    } catch (err) {
      console.error(LOG_PREFIX, 'Unhandled error in poll():', err);
    }
  }

  // ── Event dispatch ─────────────────────────────────────────────────────────
  function dispatchPicksEvent(detail) {
    document.dispatchEvent(
      new CustomEvent(EVENT_NAME, { detail: detail })
    );
  }

  // ── Bootstrap ─────────────────────────────────────────────────────────────
  console.log(LOG_PREFIX, 'Initialised. Polling every', POLL_INTERVAL_MS, 'ms.');
  poll(); // immediate first run
  setInterval(poll, POLL_INTERVAL_MS);

})();
