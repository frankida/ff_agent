/**
 * content.js — Isolated-world content script.
 *
 * Responsibilities:
 *  1. Inject injected.js into the page's MAIN world so it can access React
 *     fiber internals (window, __reactFiber$*, etc.).
 *  2. Listen for the 'fantasy-agent-picks' CustomEvent dispatched by
 *     injected.js and forward the payload to the background service worker.
 */

(function () {
  'use strict';

  // ── 1. Inject injected.js into the MAIN world ──────────────────────────────
  const script = document.createElement('script');
  script.src = chrome.runtime.getURL('injected.js');
  script.type = 'text/javascript';

  // Remove the tag after execution to keep the DOM tidy
  script.onload = function () {
    script.remove();
    console.log('[fantasy-agent:content] injected.js loaded into MAIN world.');
  };

  script.onerror = function (err) {
    console.error('[fantasy-agent:content] Failed to inject injected.js:', err);
  };

  // Append to <head> (preferred) or <html> as fallback
  (document.head || document.documentElement).appendChild(script);

  // ── 2. Listen for pick events from MAIN world ──────────────────────────────
  document.addEventListener('fantasy-agent-picks', function (event) {
    const detail = event.detail;

    console.log(
      '[fantasy-agent:content] Received fantasy-agent-picks event:',
      detail
    );

    // Forward to background service worker
    chrome.runtime.sendMessage(
      { type: 'picks', data: detail },
      function (response) {
        if (chrome.runtime.lastError) {
          // Background may be sleeping; message will be retried on next poll
          console.warn(
            '[fantasy-agent:content] sendMessage error:',
            chrome.runtime.lastError.message
          );
          return;
        }
        if (response && response.ok) {
          console.log(
            '[fantasy-agent:content] Background acknowledged pick forward.'
          );
        }
      }
    );
  });

  console.log('[fantasy-agent:content] Content script initialised.');
})();
