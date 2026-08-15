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
- `pytest tests/test_shadow_mode.py tests/test_line_ai_secretary.py -q`: 68 passed
- `pytest tests/test_alembic_revision_chain.py tests/test_shadow_mode.py tests/test_line_ai_secretary.py -q`: 69 passed
- `reject_conflicts=True`: retained on all three autopilot reservation-creation paths
- global and per-patient autopilot gates: retained
- Render Blueprint: `GEMINI_API_KEY` and `LINE_AUTOPILOT_ENABLED=true` declared for production and staging; secret values remain dashboard-managed

## Conversation reset follow-up

- Active setup and booking conversations expire after one hour of inactivity. The next message does not reuse stale draft data; setup restarts from identity input and booking restarts from menu selection with an expiration explanation.
- A dedicated Gemini classifier uses the current phase to distinguish `continue`, identity retry, booking restart, and abandonment. It treats changing a proposed time and cancelling an already confirmed reservation as `continue`, so the existing reservation flow handles them.
- Live Gemini probe results were high-confidence and correct for natural abandonment, booking restart, proposed-time change, confirmed-reservation cancellation, and identity-input correction examples.
- When Gemini is unavailable or uncertain, natural text does not reset state. Only exact quick-reply command payloads are accepted as the safe fallback.
- Conversation reset marks only the current unconfirmed request as `abandoned`; it does not create, delete, reschedule, or cancel a reservation.
- All identity steps provide an `入力をやり直す` quick reply. Before any new patient is created, the user sees both confirmation and retry choices.
- Phone numbers and birth dates are replaced with placeholders before identity-control text is sent to Gemini. Matching still uses the original input locally.

## LLM-only reply follow-up

- Removed `_is_grounded_reply` and all verbatim fact-repetition requirements. A successful Gemini reply is sent unchanged even when it omits menu, practitioner, or date facts.
- Numeric date/time contradictions are detected separately. A contradiction triggers one rewrite request; a second contradiction falls back to the emergency template.
- Missing key/API errors and repeated contradictions log `logger.error` with `reason=api_error` or `reason=contradiction`, then notify the administrator before returning a template.
- The latest six conversation messages (three round trips) are stored in `line_user_states.context_data.conversation_history` and supplied to reply composition.
- Autopilot patients now use unified LLM slot filling across `idle`, `waiting_menu`, `waiting_datetime`, and `waiting_time_duration`. Parsed date, time, menu hint, duration, and constraints are merged into the draft.
- Natural `usual` expressions and the existing `⭐️いつもの` quick reply share the same preset resolution path.
- Date-only input is acknowledged with up to three same-day availability candidates. Time-only input is acknowledged before asking only for the date.
- The legacy waiting-menu/duration/datetime branches remain present and are explicitly restricted to non-autopilot patients.
- Acceptance tests cover successful LLM text not matching fallback templates, one contradiction rewrite, API-failure alerting, natural `いつもので明日`, date-only acknowledgement, quick-reply compatibility, non-autopilot legacy behavior, and button-free natural-message booking.
- Final parser eval: LLM 45/45, intent 41/45, date 17/18, time 17/17, constraints 23/45.
- Final required regression: `pytest tests/test_shadow_mode.py tests/test_line_ai_secretary.py -q` passed 77 tests after the final identity-branch scope guard.

## Remaining environment verification

- Confirm the deployed Render service has a non-empty `GEMINI_API_KEY`; the dashboard value is not visible from this workspace.
- Run the five real LINE scenarios (new, usual, full-slot alternatives, change, cancel) with the two opted-in accounts. This requires inbound LINE webhook traffic and cannot be simulated from the local test runner.