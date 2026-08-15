# LINE autopilot voice implementation results

実施日: 2026-08-15

## Task 0

- Gemini direct probe: HTTP 200, response body `ok`
- Before implementation:
  - LLM effective calls: 45/45 (failures: 0)
  - reservation intent detection: 43/45
  - intent kind: 41/45
  - date: 17/18
  - time: 17/17
  - constraints: 18/45
  - fully failed cases: 27/45
- The first eval run exposed a real Gemini response-shape failure: a constraint was returned as an object and crashed the evaluator. Constraints are now normalized to the documented string-list contract at the parser boundary.

## Tasks D-1 and D-2

- Added situation-specific composer guidance, strict fact preservation, patient-message acknowledgement, medical-advice prohibition, and 1-3 sentence tone guidance.
- Replaced the leaking HTTP client with an `async with httpx.AsyncClient()` lifecycle.
- Added context-aware fallbacks and post-generation grounding checks. Changed dates, times, practitioner names, menu names, alternative labels, or ambiguous completion wording cause a fallback.
- Connected `confirm_slot`, `offer_alternatives`, `usual_confirm`, datetime/missing-info questions, confirmations, completion messages, slot-taken messages, and handoff messages to real-context composition in the opted-in autopilot flow.
- Kept setup identity messages and non-autopilot/shadow patient behavior unchanged.

## Task D-3

- Added one-line autopilot conversation logging with patient message, parser summary, selected situation, and sent reply.
- Low-confidence parser results do not advance to proposal or confirmation.
- Reservation messages that also require human follow-up continue through reservation handling while creating an administrator handoff notification.
- Confirmation-time change intent returns to datetime collection instead of repeating yes/no.
- Debounce no longer merges thanks or a different booking/change/cancel intent into the prior message.
- Three consecutive identical clarification situations switch the user to manual handling and notify the administrator.

Reproduced failure classes from the live-LLM eval included constraints returned as objects, casual affirmative messages misclassified as new bookings, date-only/time-only fragments, and changed/current dates being confused. Local Docker services were not running, so no local `shadow_logs` rows or real LINE-account scenarios were available for inspection during this run.

## Final verification

- LLM effective calls: 45/45 (failures: 0)
- reservation intent detection: 43/45
- intent kind: 41/45 (instruction baseline: 37/45)
- date: 17/18
- time: 17/17
- constraints: 23/45 (before: 18/45)
- fully failed cases: 22/45 (before: 27/45)
- `pytest tests/test_shadow_mode.py tests/test_line_ai_secretary.py -q`: 62 passed
- `reject_conflicts=True`: retained on all three autopilot reservation-creation paths
- global and per-patient autopilot gates: retained
- Render Blueprint: `GEMINI_API_KEY` and `LINE_AUTOPILOT_ENABLED=true` declared for production and staging; secret values remain dashboard-managed

## Remaining environment verification

- Confirm the deployed Render service has a non-empty `GEMINI_API_KEY`; the dashboard value is not visible from this workspace.
- Run the five real LINE scenarios (new, usual, full-slot alternatives, change, cancel) with the two opted-in accounts. This requires inbound LINE webhook traffic and cannot be simulated from the local test runner.