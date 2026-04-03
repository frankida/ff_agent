/**
 * background.js — Manifest V3 Service Worker.
 *
 * Responsibilities:
 *  1. Receive pick data from content.js and POST it to the local Fantasy
 *     Agent HTTP server at http://localhost:5050/picks.
 *  2. Stay alive past Manifest V3's 5-minute idle timeout via chrome.alarms.
 */

'use strict';

const SERVER_URL = 'http://localhost:5050/picks';
const LOG_PREFIX = '[fantasy-agent:background]';

// ── Keep-alive alarm ───────────────────────────────────────────────────────
// Manifest V3 service workers are terminated after ~5 minutes of inactivity.
// We schedule an alarm every 4 minutes so the worker wakes up and stays warm.
chrome.alarms.create('keepAlive', { periodInMinutes: 4 });

chrome.alarms.onAlarm.addListener(function (alarm) {
  if (alarm.name === 'keepAlive') {
    // No-op ping — just waking up the service worker
    console.debug(LOG_PREFIX, 'Keep-alive ping received.');
  }
});

// ── Message listener ───────────────────────────────────────────────────────
chrome.runtime.onMessage.addListener(function (message, sender, sendResponse) {
  if (message.type !== 'picks') {
    return false; // not our message; don't keep the channel open
  }

  console.log(LOG_PREFIX, 'Received picks message from content script:', message.data);

  // POST to local server asynchronously — must return true to keep
  // sendResponse available across the async boundary.
  forwardPicks(message.data)
    .then(function () {
      sendResponse({ ok: true });
    })
    .catch(function (err) {
      console.warn(LOG_PREFIX, 'forwardPicks failed, responding with error:', err.message);
      sendResponse({ ok: false, error: err.message });
    });

  return true; // keeps the message channel open for async sendResponse
});

// ── HTTP forwarding ────────────────────────────────────────────────────────
/**
 * POSTs the picks payload to the Fantasy Agent local server.
 * Resolves on 2xx; rejects otherwise. Never throws — all errors are caught
 * inside the message listener above.
 *
 * @param {object} data – The detail object from the fantasy-agent-picks event
 * @returns {Promise<void>}
 */
async function forwardPicks(data) {
  let response;

  try {
    response = await fetch(SERVER_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        // Simple shared secret so the server can reject rogue callers.
        // The server currently accepts all requests from localhost, so this
        // header is informational for now.
        'X-Fantasy-Agent': '1',
      },
      body: JSON.stringify(data),
    });
  } catch (networkErr) {
    // Server is not running — this is expected when the Python app is off.
    console.warn(
      LOG_PREFIX,
      'Could not reach Fantasy Agent server (is it running?):',
      networkErr.message
    );
    // Don't rethrow — we don't want the popup/content script to see an error
    // just because the server isn't up yet.
    return;
  }

  if (!response.ok) {
    const body = await response.text().catch(() => '(unreadable body)');
    throw new Error(
      `Server returned ${response.status} ${response.statusText}: ${body}`
    );
  }

  console.log(LOG_PREFIX, 'Picks forwarded successfully. Status:', response.status);
}
