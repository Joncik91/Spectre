# Spectre Glossary

Registry of every user-visible status code and load-bearing term.
Parser contract: `## <key>` starts an entry; subsequent `- field: value` lines populate it.
Status codes: dotted identifiers like `walker.init`. Terms: `term:<noun>` prefix.

---

## adr.graph_update
- kind: status
- dev: Error updating the ADR graph after writing an ADR; graph may be inconsistent.
- pm: A decision record was saved but the project map could not be updated. You may need to re-run the graph update manually.
- triggered_by: `spectre adr` graph-update subcommand.
- user_action: Check the error field; re-run `spectre adr graph-update` if needed.
- related: adr.graph_updated, adr.write
- since: v0.5.0

## adr.graph_updated
- kind: status
- dev: ADR supersedes-edge written to .graph.md; new_id replaces old_id in the graph.
- pm: The project map has been updated to reflect that the new decision replaces the old one.
- triggered_by: `spectre adr graph-update --new-id … --old-id …`.
- user_action: None — the graph is consistent.
- related: adr.write, adr.graph_update
- since: v0.5.0

## adr.write
- kind: status
- dev: ADR markdown file written to decisions/ at the given path. On error, verify write permissions on decisions/ then retry.
- pm: Your decision record has been saved.
- triggered_by: `spectre adr write` after /vision or /implement decision capture.
- user_action: If this emits as error, verify write permissions on decisions/ then retry.
- related: adr.graph_updated
- since: v0.5.0

## audit.bad_paths_json
- kind: status
- dev: JSON decode error parsing the --paths argument to the auditor CLI.
- pm: The list of file paths to audit could not be read. This is a Spectre internal error — please report it.
- triggered_by: `spectre auditor` CLI with malformed JSON --paths argument.
- user_action: Internal error; report with the error field value.
- related: audit.run, audit.summary
- since: v0.6.0

## audit.bad_paths_type
- kind: status
- dev: --paths argument parsed to a non-list type; expected a JSON array of strings.
- pm: The list of file paths to audit was the wrong shape. This is a Spectre internal error — please report it.
- triggered_by: `spectre auditor` CLI with wrong-type --paths argument.
- user_action: Internal error; report with the type field value.
- related: audit.bad_paths_json
- since: v0.6.0

## audit.bad_properties_json
- kind: status
- dev: JSON decode error parsing the --properties argument to the auditor CLI.
- pm: The spec property checks could not be parsed. This is a Spectre internal error — please report it.
- triggered_by: `spectre auditor` CLI with malformed JSON --properties argument.
- user_action: Internal error; report with the error field value.
- related: audit.run, audit.summary
- since: v0.6.0

## audit.bad_properties_type
- kind: status
- dev: --properties argument parsed to a non-list type; expected a JSON array.
- pm: The spec property checks were the wrong shape. Fix the properties: block in your spec.
- triggered_by: `spectre auditor` CLI with wrong-type --properties argument.
- user_action: Fix spec § properties: to be a JSON array of dicts (or null).
- related: audit.bad_properties_json
- since: v0.6.0

## audit.fail
- kind: status
- dev: One or more PBT-lite property checks failed for the current step; details in check= and reason= fields.
- pm: A post-step check failed — one of the expected outcomes was not produced. See the reason for details.
- triggered_by: `spectre auditor run` after a step's action, when a property assertion fails.
- user_action: Investigate the failing check; fix the step output or adjust the spec's `properties:` block. Run `spectre auditor audit-action` to re-check.
- related: audit.summary, audit.run
- since: v0.6.0

## audit.run
- kind: status
- dev: Unhandled exception during auditor execution; auditor could not complete.
- pm: The post-step checker encountered an unexpected error. This is a Spectre internal error.
- triggered_by: `spectre auditor` CLI on any unexpected exception.
- user_action: Report the error field; auditor output is unreliable for this step.
- related: audit.summary
- since: v0.6.0

## audit.scratchpad_load
- kind: status
- dev: Failed to load the scratchpad before or after running auditor checks.
- pm: Spectre could not read its progress file while running checks. This is a Spectre internal error.
- triggered_by: `spectre auditor run` when the scratchpad is missing or corrupted.
- user_action: Check that state/scratchpad.json exists and is valid JSON.
- related: audit.run
- since: v0.6.0

## audit.scratchpad_write
- kind: status
- dev: Failed to write audit results back to the scratchpad after checks completed.
- pm: Post-step check results could not be saved. Progress may be incomplete.
- triggered_by: `spectre auditor run` when scratchpad write fails after check completion.
- user_action: Check filesystem permissions on state/scratchpad.json.
- related: audit.run
- since: v0.6.0

## audit.summary
- kind: status
- dev: All PBT-lite property checks completed; checks=N passed=true|false overall verdict.
- pm: Post-step checks finished. See the passed field for the overall result.
- triggered_by: `spectre auditor run` after all property checks complete (even if some fail).
- user_action: If passed=false, investigate the audit.fail lines above.
- related: audit.fail
- since: v0.6.0

## envelope.check
- kind: status
- dev: Tier 0 envelope integrity check result; status=ok|missing|tampered.
- pm: Spectre verified the handoff package from /vision to /implement. See status for the outcome.
- triggered_by: `/implement` start — Tier 0 handoff_validator check.
- user_action: If status=missing, run /vision and lock the spec to produce an envelope. If status=tampered, re-run /vision to regenerate the seal.
- related: term:envelope
- since: v0.7.0

## eval.bad_slug
- kind: status
- dev: The spec slug passed to the evaluator does not match any file in specs/.
- pm: Spectre could not find the spec to evaluate. Check the spec name.
- triggered_by: `spectre spec_evaluator` CLI with an unknown slug.
- user_action: List specs/ and pass a valid slug.
- related: eval.run
- since: v0.5.0

## eval.clear_bundle
- kind: status
- dev: Error clearing the pre-lock eval bundle file (.eval-bundle.json) before evaluation.
- pm: Spectre could not clear a temporary evaluation file. This is a Spectre internal error.
- triggered_by: `spectre spec_evaluator` at the start of a fresh evaluation run.
- user_action: Remove state/.eval-bundle.json manually and retry.
- related: eval.run
- since: v0.5.0

## eval.envelope_written
- kind: status
- dev: Vision→implement handoff envelope JSON written and SHA-256 sealed; path= is the output file.
- pm: The handoff package from /vision to /implement has been created and sealed.
- triggered_by: `spectre eval_metadata envelope-write` after spec lock.
- user_action: None — the envelope is ready for /implement.
- related: term:envelope, eval.sidecar_written
- since: v0.7.0

## eval.run
- kind: status
- dev: Unhandled exception during spec evaluation; evaluator could not complete.
- pm: The spec review encountered an unexpected error. This is a Spectre internal error.
- triggered_by: `spectre spec_evaluator` CLI on any unexpected exception.
- user_action: Report the error field; evaluation output is unreliable.
- related: eval.bad_slug
- since: v0.5.0

## eval.sidecar_written
- kind: status
- dev: .eval.json sidecar file written next to the locked spec; contains tier results and findings.
- pm: The spec review report has been saved.
- triggered_by: `spectre eval_metadata sidecar-write` after evaluation completes.
- user_action: None — the sidecar is informational.
- related: eval.envelope_written
- since: v0.5.0

## eval_metadata.bad_payload_json
- kind: status
- dev: JSON decode error parsing the --payload argument to eval_metadata CLI.
- pm: The evaluation data payload could not be read. Re-run /vision to regenerate a valid payload.
- triggered_by: `spectre eval_metadata` CLI with malformed JSON --payload argument.
- user_action: Re-run /vision to regenerate a valid payload.
- related: eval_metadata.payload_missing
- since: v0.5.0

## eval_metadata.bad_severity_json
- kind: status
- dev: JSON decode error parsing the severity override config file.
- pm: The severity configuration file could not be read. Check that ~/.spectre/reviewer.toml is valid TOML.
- triggered_by: `spectre eval_metadata` when severity config is malformed.
- user_action: Fix ~/.spectre/reviewer.toml or remove it to use defaults.
- related: eval_metadata.config_missing
- since: v0.5.0

## eval_metadata.config_missing
- kind: status
- dev: Severity override config file (reviewer.toml) not found at expected path; using defaults.
- pm: No custom review settings found — using built-in defaults.
- triggered_by: `spectre eval_metadata` when ~/.spectre/reviewer.toml does not exist.
- user_action: None if defaults are acceptable; create ~/.spectre/reviewer.toml (see docs/SETUP.md) to customize.
- related: eval_metadata.bad_severity_json
- since: v0.5.0

## eval_metadata.envelope_write
- kind: status
- dev: Error writing the handoff envelope file.
- pm: Spectre could not create the handoff package. This is a Spectre internal error.
- triggered_by: `spectre eval_metadata envelope-write` on write failure.
- user_action: Check filesystem permissions on the state/ directory.
- related: eval.envelope_written
- since: v0.7.0

## eval_metadata.file_missing
- kind: status
- dev: A required input file for eval_metadata was not found.
- pm: A file Spectre needs for evaluation is missing. This is a Spectre internal error.
- triggered_by: `spectre eval_metadata` when an expected input file does not exist.
- user_action: Report with the path field value; re-run /vision to regenerate missing files.
- related: eval_metadata.no_input
- since: v0.5.0

## eval_metadata.no_input
- kind: status
- dev: No input provided to eval_metadata CLI; missing required argument.
- pm: The evaluation metadata command was called without required input. Pass --file <path> or pipe data via --stdin.
- triggered_by: `spectre eval_metadata` CLI called with no arguments.
- user_action: Pass --file <path> or pipe data via --stdin.
- related: eval_metadata.file_missing
- since: v0.5.0

## eval_metadata.payload_missing
- kind: status
- dev: Required --payload argument was not provided to eval_metadata CLI.
- pm: Evaluation data was not passed to the metadata writer. Verify --payload path exists and is readable.
- triggered_by: `spectre eval_metadata` CLI without required --payload flag.
- user_action: Verify --payload path exists and is readable.
- related: eval_metadata.bad_payload_json
- since: v0.5.0

## eval_metadata.sidecar_missing
- kind: status
- dev: .eval.json sidecar file not found when trying to read it for envelope creation.
- pm: The spec review report is missing. Re-run /vision to regenerate it.
- triggered_by: `spectre eval_metadata envelope-write` when .eval.json does not exist.
- user_action: Re-run /vision to regenerate the evaluation sidecar.
- related: eval.sidecar_written
- since: v0.5.0

## eval_metadata.sidecar_missing_field
- kind: status
- dev: .eval.json sidecar is present but missing a required field for envelope creation.
- pm: The spec review report is incomplete. Re-run /vision to regenerate it.
- triggered_by: `spectre eval_metadata envelope-write` when sidecar lacks a required key.
- user_action: Re-run /vision to regenerate a complete sidecar.
- related: eval_metadata.sidecar_missing
- since: v0.7.0

## eval_metadata.sidecar_write
- kind: status
- dev: Error writing the .eval.json sidecar file.
- pm: Spectre could not save the spec review report. This is a Spectre internal error.
- triggered_by: `spectre eval_metadata sidecar-write` on write failure.
- user_action: Check filesystem permissions in the specs/ directory.
- related: eval.sidecar_written
- since: v0.5.0

## eval_metadata.spec_missing
- kind: status
- dev: The spec file referenced in the envelope does not exist on disk.
- pm: The spec file is missing. Re-run /vision to lock a fresh spec.
- triggered_by: `spectre eval_metadata envelope-write` when the spec path is not found.
- user_action: Re-run /vision to produce a locked spec.
- related: eval_metadata.sidecar_missing
- since: v0.7.0

## fingerprint.scan
- kind: status
- dev: Codebase symbol walker completed; emits counts of files, functions, classes, and imports found.
- pm: Spectre has finished scanning your project's code structure.
- triggered_by: `/vision` Step 0 — fingerprint scan before spec drafting.
- user_action: None — informational; the scan feeds the spec draft.
- related: term:fingerprint
- since: v0.4.0

## hydrate.error
- kind: status
- dev: Unhandled exception in the SessionStart hydration hook; hook exits 0 to avoid blocking Claude.
- pm: Spectre encountered an error loading your session state. Your session continues but Spectre context may be missing.
- triggered_by: Unexpected exception in `bin/hydrate.py` during SessionStart.
- user_action: Check that state/scratchpad.json and specs/.active are intact; report the error field if the problem persists.
- related: hydrate.signal, hydrate.spec_summary
- since: v0.4.0

## hydrate.migrated
- kind: status
- dev: Scratchpad automatically migrated from v1 to v2 schema during SessionStart.
- pm: Spectre upgraded its progress file format. No action needed.
- triggered_by: First SessionStart after upgrading Spectre with a v1 scratchpad on disk.
- user_action: None — migration is automatic and idempotent.
- related: scratchpad.ensure_v2
- since: v0.4.0

## hydrate.signal
- kind: status
- dev: No active spec found; emits reason=no-active-spec with a hint to run /vision. Also emits is_first_run=true|false — true when specs/.active, state/scratchpad.json, state/*.walk.json, state/*.eval-result.json, and state/.spectre-welcomed are all absent.
- pm: No active project found. Run /vision to start a new spec.
- triggered_by: SessionStart when specs/.active does not exist.
- user_action: Run /vision to begin a new spec.
- related: hydrate.spec_summary, hydrate.stale_active
- since: v0.4.0

## hydrate.spec_summary
- kind: status
- dev: Active spec loaded at SessionStart; emits slug, current step, last exit code, and last command.
- pm: Your active project is loaded. Here is where you left off.
- triggered_by: SessionStart when an active spec exists and the spec file is present.
- user_action: None — context is injected automatically.
- related: hydrate.signal, term:spec
- since: v0.4.0

## hydrate.stale_active
- kind: status
- dev: specs/.active pointer exists but the referenced spec file no longer exists on disk.
- pm: Your active project file appears to have been moved or deleted. Run /vision to start a new spec or restore the file.
- triggered_by: SessionStart when specs/.active references a missing file.
- user_action: Run /vision to start a new spec or run `spectre _scratchpad reset` to clear the stale pointer.
- related: hydrate.signal
- since: v0.4.0

## hydrate.template_patches_pending
- kind: status
- dev: Template-patch proposals exist in the proposed/ directory; count= patches await review.
- pm: There are {count} suggested improvements to your spec templates waiting for review.
- triggered_by: SessionStart when template_patcher detects pending patch proposals.
- user_action: Review pending patches via `spectre templates list` and apply or dismiss them.
- related: templates.list
- since: v0.7.0

## ledger.append
- kind: status
- dev: CDLC transition event appended to the per-project ledger; kind= is the event type.
- pm: A project lifecycle event has been recorded.
- triggered_by: `spectre cdlc_ledger append` on generate/halt/implement transitions.
- user_action: None — informational audit trail.
- related: term:ledger, ledger.read
- since: v0.6.0

## ledger.bad_args
- kind: status
- dev: Invalid or missing arguments passed to the cdlc_ledger CLI.
- pm: The ledger command was called incorrectly. This is a Spectre internal error.
- triggered_by: `spectre cdlc_ledger` CLI with wrong arguments.
- user_action: Internal error; report it.
- related: ledger.append
- since: v0.6.0

## ledger.bad_payload_json
- kind: status
- dev: JSON decode error parsing the --payload argument to the ledger CLI.
- pm: The ledger payload could not be read. Check the JSON syntax in the --payload value.
- triggered_by: `spectre cdlc_ledger append` with malformed --payload JSON.
- user_action: Fix JSON syntax in --payload value.
- related: ledger.bad_payload_type
- since: v0.6.0

## ledger.bad_payload_kv
- kind: status
- dev: A key-value pair in the ledger payload is malformed or the wrong type.
- pm: A data field in the ledger payload was invalid. Use KEY=VALUE form.
- triggered_by: `spectre cdlc_ledger append` when a payload field fails validation.
- user_action: Use form KEY=VALUE (e.g. --field reason=author-arbitrated).
- related: ledger.bad_payload_json
- since: v0.6.0

## ledger.bad_payload_type
- kind: status
- dev: --payload argument parsed to a non-dict type; expected a JSON object.
- pm: The ledger payload was the wrong shape. Check the --ledger-path exists and is readable.
- triggered_by: `spectre cdlc_ledger append` when payload is not a JSON object.
- user_action: Verify --ledger-path exists and is readable.
- related: ledger.bad_payload_json
- since: v0.6.0

## ledger.read
- kind: status
- dev: Error reading the CDLC ledger file.
- pm: Spectre could not read the project lifecycle log. This is a Spectre internal error.
- triggered_by: `spectre cdlc_ledger read` on read failure.
- user_action: Check that the ledger file exists and is valid JSON.
- related: ledger.append, term:ledger
- since: v0.6.0

## observation.find_recurrences
- kind: status
- dev: Error finding recurrence patterns in the halt observation store.
- pm: Spectre could not analyze halt patterns. The observations store may be corrupt.
- triggered_by: `spectre observations find-recurrences` on unexpected exception.
- user_action: Verify the observations store is intact; try deleting state/.observations.json and retrying.
- related: observation.record
- since: v0.7.0

## observation.record
- kind: status
- dev: Halt observation recorded; fingerprint= is the first 12 chars of the SHA-256 halt fingerprint.
- pm: A blocked action has been logged for pattern analysis.
- triggered_by: `spectre observations record-halt` after a tier gate fires.
- user_action: None — Spectre uses this data to detect recurring halts and propose template patches.
- related: term:fingerprint, term:tier-3
- since: v0.7.0

## personal_rules.adopt
- kind: status
- dev: Personal halt-override rule written to ~/.spectre/personal_rules.toml for the given classifier label and fingerprint.
- pm: Your override preference has been saved. Spectre will no longer halt for this action type.
- triggered_by: User approving an action and choosing to persist the override.
- user_action: None — the rule is stored.
- related: personal_rules.brake
- since: v0.4.1

## personal_rules.brake
- kind: status
- dev: Sandbox-paradox brake triggered; session_count= halt approvals in this session exceeds max=.
- pm: You have approved many halts in this session. Spectre is slowing down to protect you from approving something risky by accident. Check the remediation field for next steps.
- triggered_by: User approving more than the configured maximum halt count in a single session.
- user_action: Follow the remediation= hint; review what you are approving before continuing.
- related: personal_rules.adopt, term:tier
- since: v0.4.1

## personal_rules.session_count
- kind: status
- dev: Error reading the session halt count from the personal rules store.
- pm: Spectre could not read your session approval count. This is a Spectre internal error.
- triggered_by: `spectre personal_rules session-count` on read failure.
- user_action: Report the error field.
- related: personal_rules.brake
- since: v0.4.1

## scratchpad.clear_pending
- kind: status
- dev: Error clearing the pending adoption prompt from the scratchpad.
- pm: Spectre could not clear a saved prompt. This is a Spectre internal error.
- triggered_by: `spectre _scratchpad clear-pending` on write failure.
- user_action: Check filesystem permissions on state/scratchpad.json.
- related: scratchpad.prompt_cleared, scratchpad.no_track_to_clear
- since: v0.4.0

## scratchpad.ensure_v2
- kind: status
- dev: Scratchpad schema ensure-v2 operation completed; result= is created|exists|migrated. On error, delete state/scratchpad.json and re-run /vision.
- pm: Spectre's progress file is ready.
- triggered_by: `spectre _scratchpad ensure-v2` during setup or migration.
- user_action: If this emits as error, delete state/scratchpad.json and re-run /vision.
- related: hydrate.migrated
- since: v0.4.0

## scratchpad.get_pending
- kind: status
- dev: Error reading the pending adoption prompt from the scratchpad.
- pm: Spectre could not read a saved prompt. This is a Spectre internal error.
- triggered_by: `spectre _scratchpad get-pending` on read failure.
- user_action: Check that state/scratchpad.json is valid JSON.
- related: scratchpad.pending_prompt, scratchpad.no_pending_prompt
- since: v0.4.0

## scratchpad.no_pending_prompt
- kind: status
- dev: No pending adoption prompt found in the scratchpad for the given track.
- pm: There is no saved question waiting for your answer in this track.
- triggered_by: `spectre _scratchpad get-pending` when no pending prompt exists.
- user_action: None — the track has no queued prompt.
- related: scratchpad.pending_prompt
- since: v0.4.0

## scratchpad.no_track_to_clear
- kind: status
- dev: clear-pending was called but no matching track was found in the scratchpad.
- pm: Spectre tried to clear a saved prompt but found nothing to clear.
- triggered_by: `spectre _scratchpad clear-pending` when the track does not exist.
- user_action: None — idempotent; the state is already clear.
- related: scratchpad.prompt_cleared
- since: v0.4.0

## scratchpad.pending_adoption_set
- kind: status
- dev: Pending halt-override adoption prompt written to the scratchpad for the given track.
- pm: Spectre has saved a question for you to answer about approving a repeating halt.
- triggered_by: `spectre _scratchpad set-pending` when a recurring halt is detected.
- user_action: Answer the prompt that will appear at the next step.
- related: scratchpad.pending_prompt, personal_rules.adopt
- since: v0.4.0

## scratchpad.pending_prompt
- kind: status
- dev: Pending adoption prompt found; fingerprint= and label= identify the halt class awaiting approval.
- pm: There is a saved question about a repeating halt waiting for your answer.
- triggered_by: `spectre _scratchpad get-pending` when a pending prompt exists.
- user_action: Answer yes or no to the displayed prompt to store or dismiss the override.
- related: scratchpad.no_pending_prompt, personal_rules.adopt
- since: v0.4.0

## scratchpad.prompt_cleared
- kind: status
- dev: Pending adoption prompt successfully cleared from the scratchpad.
- pm: The saved question has been dismissed.
- triggered_by: `spectre _scratchpad clear-pending` after successfully removing the prompt.
- user_action: None — the prompt has been cleared.
- related: scratchpad.no_track_to_clear
- since: v0.4.0

## scratchpad.reset
- kind: status
- dev: Scratchpad reset to initial state with the given active_spec; all track progress cleared. On error, verify state/ exists and is writable.
- pm: Spectre's progress has been reset. A new spec is now active.
- triggered_by: `spectre _scratchpad reset` when a new spec is locked.
- user_action: If this emits as error, verify state/ exists and is writable.
- related: term:scratchpad
- since: v0.4.0

## scratchpad.set_pending
- kind: status
- dev: Error writing the pending adoption prompt to the scratchpad.
- pm: Spectre could not save a question for later. This is a Spectre internal error.
- triggered_by: `spectre _scratchpad set-pending` on write failure.
- user_action: Check filesystem permissions on state/scratchpad.json.
- related: scratchpad.pending_adoption_set
- since: v0.4.0

## templates.import_builtin
- kind: status
- dev: Built-in template copied into specs/<slug>.spec.md.draft; name= is the builtin name, slug= is the target slug, path= is the written draft path. On error (reason=exists), the draft already exists — choose a different --slug or delete the existing draft.
- pm: The built-in template has been copied into your project as a draft spec. Proceed with /vision to complete the spec.
- triggered_by: `spectre templates import-builtin --name <name> --slug <slug>` subcommand.
- user_action: If this emits as error with reason=exists, choose a different --slug or delete the existing draft file.
- related: templates.list
- since: v0.9.0

## templates.list
- kind: status
- dev: Template list operation completed; count= templates found in the store (includes user templates and built-in templates with kind=builtin).
- pm: There are {count} spec templates available.
- triggered_by: `spectre templates list` subcommand.
- user_action: None — informational listing.
- related: hydrate.template_patches_pending, templates.import_builtin
- since: v0.7.0

## tier.classify
- kind: status
- dev: Persistence-tier classification result; tier= is silent|repo|host|network, reasons= explains the match. On error, add the step's action to the spec and retry.
- pm: The action has been classified. The tier field shows how risky it is.
- triggered_by: `spectre tier classify` or `spectre tier evaluate-action` subcommands.
- user_action: None for ok result. If this emits as error, add the step's action to the spec and retry.
- related: tier.gate, tier.should_halt, term:tier
- since: v0.3.0

## tier.evaluate
- kind: status
- dev: Unhandled exception during tier evaluate-action; evaluator could not complete.
- pm: The action risk classifier encountered an unexpected error. This is a Spectre internal error.
- triggered_by: `spectre tier evaluate-action` on unexpected exception.
- user_action: Report the error field.
- related: tier.classify
- since: v0.3.0

## tier.gate
- kind: status
- dev: should-halt decision result; halt=true|false based on tier and personal rules.
- pm: Spectre has decided whether to pause for your approval. halt=true means it will wait.
- triggered_by: `spectre tier should-halt` subcommand.
- user_action: If halt=true, Spectre will present the action for your review before executing.
- related: tier.classify, tier.should_halt, term:tier
- since: v0.3.0

## tier.should_halt
- kind: status
- dev: Error in the should-halt decision path; tier or personal-rules lookup failed.
- pm: Spectre could not determine whether to pause. This is a Spectre internal error.
- triggered_by: `spectre tier should-halt` on unexpected exception.
- user_action: Report the error field.
- related: tier.gate
- since: v0.3.0

## tier3.budget
- kind: status
- dev: Instrumentation line emitted once per evaluate() call; reports Tier-3 LLM call volume and exemplar injection count. calls= is always 1 (exemplars are injected into a single call, not multiplied). Suppressed by SPECTRE_QUIET=1.
- pm: The AI deep-reviewer ran once and checked the spec against its examples.
- triggered_by: `llm_judge.evaluate()` after the Tier-3 contradiction-detection call completes.
- user_action: None — informational only.
- related: tier.evaluate, term:tier-3, term:exemplar
- since: v1.1.0

## tier3.run-fingerprint
- kind: status
- dev: SHA-256 fingerprint of all Tier-3 run inputs — provider, model_id, temperature, top_p, seed_if_set, system_prompt_hash (sha256 of substituted prompt), exemplar_set_hash (sha256 of sorted bound exemplar slugs), spec_text_hash (sha256 of locked spec body), judge_config_hash (sha256 of model+base_url+budget+timeouts). Emitted once per evaluate() call before the API request. hash= is a 16-char prefix for readability; hash_full= is the canonical 64-char digest to diff across runs. Suppressed by SPECTRE_QUIET=1. Diff hash_full across runs: identical hash → same inputs → non-determinism is provider instability; different hash → input drift (prompt/spec/config changed).
- pm: A fingerprint of the AI reviewer's inputs was recorded so you can tell if different AI responses came from a changed spec or from the AI itself behaving inconsistently.
- triggered_by: `llm_judge.evaluate()` before the Tier-3 API call, after budget check passes.
- user_action: None — informational only. Compare hash_full across runs to diagnose non-determinism.
- related: tier3.budget, tier.evaluate, term:tier-3
- since: v1.2.0

## track.acquire
- kind: status
- dev: Resource lock acquired from the supervisor daemon for the given resource= ID.
- pm: Spectre has reserved the resource needed for this step.
- triggered_by: `/implement` step execution when the step declares resources:.
- user_action: None — the lock is held until the step completes.
- related: track.release, track.queue, term:track
- since: v0.5.0

## track.bad_resources
- kind: status
- dev: The --resources argument could not be parsed; expected a comma-separated list of resource IDs.
- pm: The resource list for this step is malformed. This is a Spectre internal error.
- triggered_by: `spectre track acquire` with malformed --resources argument.
- user_action: Internal error; report it.
- related: track.acquire
- since: v0.5.0

## track.queue
- kind: status
- dev: Resource lock request queued; another track holds resource= at position= in the wait list.
- pm: Spectre is waiting for another track to finish using a shared resource. It will continue automatically when the resource is free.
- triggered_by: `/implement` when another parallel track holds the requested resource lock.
- user_action: Wait for the holding track to release; or pass --skip-queue to bypass if urgent.
- related: track.acquire, track.release
- since: v0.5.0

## track.release
- kind: status
- dev: Resource lock released back to the supervisor daemon for the given resource= ID.
- pm: Spectre has released the reserved resource.
- triggered_by: After a step completes (successfully or with error), the lock is released.
- user_action: None — the resource is now available to other tracks.
- related: track.acquire
- since: v0.5.0

## track.supervisor_spawn
- kind: status
- dev: Error spawning the supervisor daemon for resource lock management.
- pm: Spectre could not start its resource coordinator. This is a Spectre internal error.
- triggered_by: `spectre track acquire` when the supervisor UDS socket cannot be started.
- user_action: Report the error field; retry /implement.
- related: track.acquire, term:track
- since: v0.5.0

## venv.ensure
- kind: status
- dev: Managed Python venv creation or verification completed; python= is the venv interpreter path.
- pm: The project's Python environment is ready.
- triggered_by: `spectre managed_venv ensure` before steps that require a Python venv.
- user_action: None — the venv is ready to use.
- related: venv.pip_install
- since: v0.6.0

## venv.pip_install
- kind: status
- dev: pip install completed inside the managed venv; status=ok.
- pm: Python packages have been installed in the project environment.
- triggered_by: `spectre managed_venv pip-install` step execution.
- user_action: None — packages are installed.
- related: venv.ensure
- since: v0.6.0

## verification-too-shallow-for-claim
- kind: finding
- dev: Tier-1 warn. Step why-clause names behavioral semantics (trigger, prevent, ensure, validate, enforce, coalesce, refuse, halt, debounce, atomic) but verification is structural-only (test -f / grep -q / test -d possibly chained with &&). An implementing agent could ship a no-op symbol with the claimed name and pass the check. Augment the verification to exercise the behavior.
- pm: The step claims something will happen, but the test only checks that a file or symbol exists — not whether it actually does the thing.
- triggered_by: `spec_ast._check_verification_depth` during Tier-1 evaluation.
- user_action: Replace or augment verification with a runtime test that exercises the named behavior.
- related: soft-verification, term:tier-1
- since: v1.1.0

## walker.answer
- kind: status
- dev: Concern answer recorded; id= identifies the concern, round_count= is the current round number.
- pm: Your answer has been recorded. Spectre will use it to refine the spec.
- triggered_by: `walker answer-concern` after the user replies to a concern question.
- user_action: None — Spectre will surface the next question or recommend stopping.
- related: walker.init, walker.recommend-stop, term:concern
- since: v0.4.0

## walker.answer_failed
- kind: status
- dev: answer-concern failed because the concern ID was not found in the pending or asked lists.
- pm: Spectre could not record your answer — the question ID was not recognised. This is a Spectre internal error.
- triggered_by: `walker answer-concern` with an unknown concern ID.
- user_action: Run `spectre walker get-state --json` to list valid concern IDs then retry.
- related: walker.answer
- since: v0.4.0

## walker.bad_oq_id
- kind: status
- dev: defer-open-question called with an open-question ID that does not exist in the walk state.
- pm: The open question ID to defer was not found. This is a Spectre internal error.
- triggered_by: `walker defer-open-question` with an unknown oq-N ID.
- user_action: Run `spectre walker get-state --json` to list valid IDs.
- related: walker.open-question-deferred
- since: v0.6.0

## walker.concern
- kind: status
- dev: PROMPT emitted by peek-pending for each pending concern; id=, round=, prompt= (concern summary), options= (comma-separated prefab choices, omitted when empty). In --json mode routed to stderr; in text mode emitted to stdout after the RESULT walker.peek line.
- pm: Spectre is asking you a question about your spec. Answer with the number of your choice or type a free-form answer.
- triggered_by: `walker peek-pending` whenever a pending concern exists.
- user_action: Answer the question shown in the prompt= field. If options= is present, pick a numbered choice or type the option token.
- related: walker.peek, walker.concern_appended, term:concern
- since: v0.9.0

## walker.concern_appended
- kind: status
- dev: New concern appended to the pending list; id= is the new concern's identifier.
- pm: A new question has been added to the interview queue.
- triggered_by: `walker append-concern` during dynamic concern generation.
- user_action: None — Spectre will surface this concern in the next round.
- related: walker.peek, term:concern
- since: v0.4.0

## walker.duplicate_id
- kind: status
- dev: append-concern rejected because the given id already exists in pending, asked, or answered.
- pm: A duplicate question ID was detected and rejected. This is a Spectre internal error.
- triggered_by: `walker append-concern` with an ID that already exists in walk state.
- user_action: Internal error; report it.
- related: walker.concern_appended
- since: v0.4.0

## walker.empty
- kind: status
- dev: peek-pending returned no concerns; all concerns are answered, stale, or the pending list is empty.
- pm: There are no more questions for this round.
- triggered_by: `walker peek-pending` when no pending concerns remain.
- user_action: None — Spectre will proceed to the stop or yield decision.
- related: walker.peek, walker.stop
- since: v0.4.0

## walker.evaluator_failed
- kind: status
- dev: yield-check triggered a spec_evaluator run that raised an unhandled exception.
- pm: The per-round spec review failed. This is a Spectre internal error.
- triggered_by: `walker yield-check` when spec_evaluator.evaluate raises.
- user_action: Check spec syntax; run /vision to re-initialize if the spec is corrupt.
- related: walker.yield, walker.yield_skipped
- since: v0.4.0

## walker.init
- kind: status
- dev: Walker state machine initialized or resumed; rounds= completed so far, pending= active concerns, stop= stop reason or none.
- pm: The interview has started. There are {pending} questions waiting for you.
- triggered_by: First `/vision` invocation on a new spec, or resumption of an existing walk.
- user_action: None — Claude will surface the first question next.
- related: walker.answer, walker.yield, walker.stop
- since: v0.4.0

## walker.open-question-deferred
- kind: status
- dev: Open question oq-N deferred to an ADR; it will not block the author-arbitrated stop.
- pm: The open question has been parked in a decision record and will not block you from stopping the interview.
- triggered_by: `walker defer-open-question` after the user chooses to resolve an OQ via an ADR.
- user_action: None — the ADR has been written; you may stop the interview.
- related: walker.bad_oq_id, adr.write
- since: v0.6.0

## walker.open-questions-detected
- kind: status
- dev: Open questions parsed from the spec intent at init-or-resume; count= questions found, ids= their IDs.
- pm: Spectre found {count} open questions marked in your intent. It will track them through the interview.
- triggered_by: `walker init-or-resume` when the intent text contains open: or unresolved: markers.
- user_action: None — Spectre will surface these as concerns during the interview.
- related: walker.init
- since: v0.6.0

## walker.peek
- kind: status
- dev: peek-pending returned the next concern to ask; id=, kind=, receiver=, summary= fields included.
- pm: Here is the next question Spectre needs you to answer.
- triggered_by: `walker peek-pending` when at least one pending concern exists.
- user_action: Answer the question surfaced by the skill.
- related: walker.empty, term:concern
- since: v0.4.0

## walker.persist
- kind: status
- dev: Error persisting walker state to disk; the walk state may be lost.
- pm: Spectre could not save the interview state. This is a Spectre internal error.
- triggered_by: Any walker command that writes state, when the write fails.
- user_action: Verify write permissions on state/ then retry the last command.
- related: walker.init
- since: v0.4.0

## walker.recommend-stop
- kind: status
- dev: Coverage threshold reached; emitted exactly once on the False→True transition. reason=coverage-complete.
- pm: Spectre has gathered enough information. You can stop the interview now by typing "stop" or continue for more depth.
- triggered_by: `walker answer-concern` when computed coverage crosses the stop threshold for the first time.
- user_action: You may stop the interview (`walker stop --reason author-arbitrated`) or continue.
- related: walker.stop, term:yield
- since: v0.4.0

## walker.state
- kind: status
- dev: get-state summary line; rounds=, answered=, pending=, stop= fields.
- pm: Here is the current interview status.
- triggered_by: `walker get-state` without --json flag.
- user_action: None — informational snapshot.
- related: walker.init
- since: v0.4.0

## walker.state_load
- kind: status
- dev: Error loading walker state from disk; the state file may be missing or corrupted.
- pm: Spectre could not load the interview state. This is a Spectre internal error.
- triggered_by: Any walker command that reads state, when load fails with a ValueError.
- user_action: Run /vision to initialize a new walk; or check that the walk state file is valid JSON.
- related: walker.state_missing
- since: v0.4.0

## walker.state_missing
- kind: status
- dev: Walker state file does not exist at the expected path; no active walk session.
- pm: No active interview session found. Run /vision to start a new one.
- triggered_by: Any walker command that requires existing state, when load returns None.
- user_action: Run /vision to start a new walk.
- related: walker.init
- since: v0.4.0

## walker.stop
- kind: status
- dev: Walk stopped with the given reason=; stop_reason recorded in state.
- pm: The interview has been stopped. Spectre will now draft the spec.
- triggered_by: `walker stop` with a valid stop reason (author-arbitrated, tier3-yield-converged, max-rounds, per-receiver-exhausted).
- user_action: None — Spectre proceeds to spec drafting and evaluation.
- related: walker.recommend-stop, term:spec
- since: v0.4.0

## walker.unknown_kind
- kind: status
- dev: append-concern rejected because the given kind is not in KNOWN_CONCERN_KINDS.
- pm: An invalid question type was used. This is a Spectre internal error.
- triggered_by: `walker append-concern` with an unrecognised kind value.
- user_action: Internal error; report it.
- related: walker.concern_appended
- since: v0.4.0

## walker.yield
- kind: status
- dev: yield-check completed a Tier 3 DeepSeek evaluation round; new_t3= new finding count, history= last 5 round counts.
- pm: Spectre ran a background review round. It will keep asking questions until the review stabilises.
- triggered_by: `walker yield-check` after each answer round when a draft exists.
- user_action: None — Spectre manages the yield loop automatically.
- related: walker.yield_skipped, term:yield, term:tier-3
- since: v0.4.0

## walker.yield_skipped
- kind: status
- dev: yield-check skipped; reason= is no-walk-state, draft-missing, or round_count=0.
- pm: The background review was skipped. See the reason field.
- triggered_by: `walker yield-check` when prerequisites for a Tier 3 run are not met.
- user_action: None — will retry automatically when prerequisites are met.
- related: walker.yield
- since: v0.4.0

## walker.coverage
- kind: status
- dev: Full coverage snapshot; answered=, pending=, deferred=, undefined-invariants=, recommended-stop=yes|no, rounds= fields.
- pm: Here is a summary of how much the interview has covered. See recommended-stop to know if you can stop now.
- triggered_by: `walker stop`, `walker coverage`, or per-round under SPECTRE_VERBOSE=1.
- user_action: If recommended-stop=yes, you may stop the interview. Otherwise continue answering questions.
- related: walker.recommend-stop, walker.stop
- since: v0.4.0

## walker.open-questions-unresolved
- kind: status
- dev: author-arbitrated stop refused because open questions remain unresolved; count= and ids= listed.
- pm: You cannot stop the interview yet — {count} open questions are still unresolved. Resolve or defer them first.
- triggered_by: `walker stop --reason author-arbitrated` when unresolved open questions exist.
- user_action: Answer each question or run `spectre walker defer-open-question --id <oq-id> --adr <slug>` to defer to an ADR.
- related: walker.open-questions-detected, walker.open-question-deferred
- since: v0.6.0

## vision.coverage_continue
- kind: status
- dev: Emitted at lock-attempt when walker coverage reports recommended_stop=no; prompts operator to confirm continuing to lock despite incomplete coverage. options=yes,refine.
- pm: The interview may not have covered all areas of your spec. You can continue to lock or refine more answers first.
- triggered_by: `spectre _status emit prompt vision.coverage_continue` in the /vision Lock phase when coverage is incomplete.
- user_action: Pick 1 (yes) to proceed to lock anyway, or 2 (refine) to continue the interview.
- related: walker.coverage, vision.lock_confirm
- since: v0.9.0

## vision.lock_confirm
- kind: status
- dev: Emitted at the draft-confirmation moment to request operator approval before locking the spec. draft= path, summary= one-line, options=yes,refine,cancel.
- pm: Your spec draft is ready. Confirm to lock it, request changes, or cancel.
- triggered_by: `spectre _status emit prompt vision.lock_confirm` in the /vision Draft phase after the draft is written.
- user_action: Pick 1 (yes) to lock, 2 (refine "<change>") to request a change, or 3 (cancel) to discard.
- related: vision.coverage_continue, vision.warn_proceed
- since: v0.9.0

## vision.warn_proceed
- kind: status
- dev: Emitted at the evaluator gate when max_severity==warn; prompts operator whether to proceed to lock despite warn-severity findings. warn_count=N, options=yes,refine,cancel.
- pm: The spec review found {warn_count} warning(s). You can lock now, request changes, or cancel.
- triggered_by: `spectre _status emit prompt vision.warn_proceed` in the /vision Evaluator gate when max_severity==warn.
- user_action: Pick 1 (yes) to lock with warnings, 2 (refine "<change>") to address them, or 3 (cancel) to discard.
- related: vision.lock_confirm, eval.summary
- since: v0.9.0

## wizard.config_migrated
- kind: status
- dev: Stale reviewer.toml detected and migrated; backup= is the saved backup filename.
- pm: Spectre updated your review settings file. A backup was saved as shown in the backup field.
- triggered_by: `spectre setup_wizard` when an existing reviewer.toml is from a stale version.
- user_action: None — migration is automatic; inspect the backup if needed.
- related: wizard.setup
- since: v0.6.0

## wizard.setup
- kind: status
- dev: Setup wizard completed; result= is enabled|exists|setup-skipped, target= is the configured path.
- pm: Spectre's initial setup is done.
- triggered_by: `spectre setup_wizard` on first install or re-run.
- user_action: None — setup is complete.
- related: term:spec
- since: v0.5.0

## wizard.substrate
- kind: status
- dev: §8.2 cognitive-substrate wizard error; reason= describes what went wrong (invalid flags, missing flags, validation error).
- pm: The project context wizard encountered an error. See the reason field for details.
- triggered_by: `spectre substrate_wizard run` on validation or flag errors.
- user_action: Check the reason field; re-run with correct flags or in interactive mode.
- related: wizard.setup
- since: v0.7.0

## wizard.tier3_skipped
- kind: status
- dev: Tier 3 DeepSeek reviewer skipped during setup because no API key was found; reason= names the missing env var.
- pm: The AI reviewer (Tier 3) was not set up because no API key was found. You can add one later by setting the environment variable named in the reason field.
- triggered_by: `spectre setup_wizard` when the required API key env var is not set.
- user_action: Set the API key env var and re-run the setup wizard to enable Tier 3 review.
- related: wizard.setup, term:tier-3
- since: v0.6.0

---

## term:walker
- kind: term
- dev: State machine that drives the /vision interrogation loop. Owns walk state, concern lifecycle, yield counters, and stop-reason logic.
- pm: The interviewer. Asks you questions about what you want built until it has enough to write a spec.
- related: term:concern, term:yield, term:spec

## term:concern
- kind: term
- dev: A single structured question in the walker's pending queue. Has an id, kind (edge-case, assumption-surface, etc.), receiver (human/implement/tier3/deterministic), and summary text.
- pm: A question the interviewer needs you to answer before drafting the spec.
- related: term:walker, walker.peek, walker.answer

## term:scratchpad
- kind: term
- dev: Per-project JSON file at state/scratchpad.json tracking active spec, current step, last command, exit code, and audit history. v2 schema supports named tracks.
- pm: Spectre's memory of where you left off. Updated after every step.
- related: term:track, term:spec, scratchpad.reset

## term:envelope
- kind: term
- dev: SHA-256-sealed JSON bundle created at /vision lock, consumed at /implement start (Tier 0 check). Contains spec path, sidecar path, spec_sha256, and sidecar_sha256.
- pm: A tamper-evident package that carries the reviewed spec from /vision to /implement. Spectre checks it has not been altered before executing anything.
- related: eval.envelope_written, envelope.check

## term:tier
- kind: term
- dev: Side-effect classification for a shell command. Four levels: silent (no filesystem writes), repo (project files only), host (system paths or /etc, /usr, /opt), network (outbound calls).
- pm: How risky an action is. Higher tiers require your approval before Spectre will run the command.
- related: tier.classify, tier.gate, term:tier-3

## term:fingerprint
- kind: term
- dev: SHA-256 hash computed from the action text and classifier label, uniquely identifying a halt class. Used to deduplicate observations and key personal-rules overrides.
- pm: A unique signature for a type of blocked action. Spectre uses it to recognise repeat halts and offer to remember your approval.
- related: observation.record, personal_rules.adopt

## term:drift
- kind: term
- dev: Accumulated divergence between the active spec's intent and the current implementation state. Measured periodically; triggers a warning when the delta is too large.
- pm: How far the project has wandered from the original plan. Spectre flags it when the gap gets too wide.
- related: term:spec, term:scratchpad

## term:ledger
- kind: term
- dev: Append-only JSONL event log at state/cdlc-ledger.jsonl recording generate/halt/implement transitions with timestamps and payloads.
- pm: A permanent record of every major project lifecycle event — when specs were written, when halts occurred, when steps were implemented.
- related: ledger.append, term:cdlc

## term:track
- kind: term
- dev: Named parallel-execution lane within a spec. Each track has its own step counter, resource locks, and scratchpad slot. Default track is named "default".
- pm: A parallel work stream. Spectre can run multiple tracks at once, each working on a different part of the spec.
- related: term:scratchpad, track.acquire, track.release

## term:yield
- kind: term
- dev: Per-round count of new Tier 3 findings from the DeepSeek adversarial reviewer. When the yield delta converges to zero across multiple rounds, the walker considers stopping.
- pm: The number of new issues the background reviewer found this round. When it reaches zero for several rounds in a row, the interview is considered complete.
- related: walker.yield, term:walker, term:tier-3

## term:spec
- kind: term
- dev: The locked .spec.md file — a structured markdown document containing §1 intent, §2–§7 design sections, §8.1 hard contract, and §8.2 cognitive-substrate contract. Locked atomically via specs/.active.
- pm: The project plan. A structured document that describes what to build, why, how to verify each step, and what risks to guard against.
- related: term:lock, term:envelope, hydrate.spec_summary

## term:lock
- kind: term
- dev: Atomic flip of specs/.active to point at a newly-drafted spec file, marking it as the active mission. Triggers envelope creation and scratchpad reset.
- pm: The moment a spec is officially adopted as the active project plan. After locking, Spectre can execute steps from it.
- related: term:spec, term:envelope, scratchpad.reset

## term:findings
- kind: term
- dev: Evaluator output items produced by Tier 1, Tier 2, or Tier 3 review. Each finding has a severity (warn or block), a kind (e.g. soft-verification, coverage-gap, contradiction), and a message.
- pm: Issues found during spec review. Block-severity findings must be resolved before the spec can be locked.
- related: term:tier-3, eval.sidecar_written

## term:tier-3
- kind: term
- dev: The DeepSeek adversarial reviewer (deepseek-v4-flash). Runs the contradiction-tuple protocol — 10 finding kinds plus a CoT faithfulness cite-and-verify pass and adversarial-pathway rubric. Called once per yield-check round during the walker loop.
- pm: The AI reviewer that looks for hidden flaws in your spec. It argues against the plan and flags contradictions, missing paths, and unrealistic assumptions.
- related: term:yield, walker.yield, term:findings

## term:cdlc
- kind: term
- dev: Content-Driven Lifecycle Cycle — the generate→halt→implement transition model. Spectre records every transition to the ledger for auditability.
- pm: The project lifecycle model Spectre follows: write a plan, review it, then implement it step by step. Each phase transition is logged.
- related: term:ledger, term:spec

## term:view
- kind: term
- dev: One of six receiver-calibrated perspectives a v1.0 spec carries — implementing-agent, product-input, product-output, human-user, integrator, operator. Each view declares its own substrate block (§8.x) and may declare contracts (§§9-13).
- pm: A perspective on the product. v1.0 covers six perspectives: the AI that builds it, who feeds it, who reads it, who uses it, who integrates with it, and who runs it. Each gets its own section in the spec.
- related: term:receiver, term:exemplar, term:contract-type

## term:receiver
- kind: term
- dev: An entity that receives output or contract obligations from the product the spec describes. v0.9 modeled one receiver (the implementing agent); v1.0 names six.
- pm: Anyone or anything that interacts with the product — the AI building it, the user typing into it, the system reading its output. Spectre's v1.0 spec captures the obligations toward each.
- related: term:view, term:propagation

## term:exemplar
- kind: term
- dev: A curated catalog entry naming a real tool whose conventions for a given view-type (help-text, error-text, log-format, api-shape, observability) have been documented. The frontmatter conventions list becomes Tier-3's machine contract; the body explains operationally what the conventions mean.
- pm: A worked example from a well-known tool. Picking `curl` for help-text style means the AI builds help text that follows curl's conventions. The catalog has 17 exemplars across 5 view-types as of v1.0.
- related: term:axis, term:taxonomy-version, term:contract-type

## term:axis
- kind: term
- dev: One dimension of variation within a view-type's design space (e.g. help-text has verbosity, structure, example-density). Each exemplar declares its axis values in frontmatter so operators see what they're choosing between, not just from.
- pm: A design choice within a view-type. When picking between exemplars, the axes show what differs (terse vs verbose, flat vs sectioned, etc.) so you can compare meaningfully.
- related: term:exemplar, term:taxonomy-version

## term:taxonomy-version
- kind: term
- dev: A versioned axis taxonomy per view-type, declared in docs/exemplars/<view-type>/axes.yml. Specs pin the taxonomy version at lock time so post-v1.0 axis additions don't silently invalidate older specs.
- pm: The version of the catalog's design-choice list. Pinning prevents future catalog updates from quietly changing what an existing spec means.
- related: term:axis, term:exemplar

## term:contract-type
- kind: term
- dev: One of three contract families a v1.0 view section may declare — mechanical (schemas, exact strings, structural shapes; Tier-1 AST check), coverage (must-include lists; Tier-1 presence check), exemplar-bindings (style adherence; Tier-3 LLM review).
- pm: How a spec section commits to its receiver. Spec sections can name schemas (Tier-1 checks), required content categories (Tier-1 checks), or pick exemplars (Tier-3 LLM checks). Mix and match.
- related: term:view, term:exemplar

## term:metis
- kind: term
- dev: Accumulated practical know-how (per the framework Spectre is built on) that has solved a recurring problem in production tooling. The metis catalog (`docs/exemplars/`) curates which existing tools encode useful metis for each receiver class. Spectre does not extract metis — it specifies which existing metis applies to the spec at hand.
- pm: The practical wisdom baked into tools that have been used at scale. Spectre's v1.0 catalog points your spec at existing best-of-breed examples instead of asking you to invent conventions.
- related: term:exemplar, term:propagation

## term:propagation
- kind: term
- dev: A context-transfer event between two receivers in the framework Spectre is built on. Each propagation event is where context can be lost (the implementing agent assumes one thing, the human user expects another). v1.0's six-view model exists to surface and constrain each propagation event.
- pm: Any point where information about the product travels from one party to another (AI to user, product to operator, etc.). The six-view spec makes sure each of these transitions is documented.
- related: term:view, term:receiver

## term:sanitized-input
- kind: term
- dev: An optional step field (`sanitized-input: [contract-entry, ...]`) that declares the listed artifact versions have been cleaned before this step consumes them. Clears taint of the *current artifact version* at the step's consumption boundary. Unlike `sanitizes:` (which marks this step's own output as clean), `sanitized-input:` asserts that an upstream process already sanitized the input. Artifact-version invariant: a subsequent `produces:` of the same path mints a new version that starts tainted again — a prior `sanitized-input:` declaration does not carry over to re-written versions.
- pm: A field you add to a step to tell Spectre "I know this input was cleaned by a prior step." Use it when the scrubbing happened upstream and the current step just consumes a clean artifact. Different from `sanitizes:`, which says "this step's output is the clean version."
- related: term:taint, term:artifact-version

## term:taint
- kind: term
- dev: The per-artifact-version flag the `untrusted-flow-unguarded` check tracks. An artifact is tainted when produced by a step that declares `untrusted-input: yes` or receives tainted inputs. Taint is cleared by (a) `sanitizes:` on the producing step's output, or (b) `sanitized-input:` on the consuming step for that artifact. Each new `produces:` of a path mints a fresh artifact version with its own independent taint state.
- pm: Whether Spectre considers a file or artifact to carry unvalidated external data. Tainted artifacts flag a warning if they flow into dangerous operations (file writes, shell commands, network calls) without a declared sanitization step.
- related: term:sanitized-input, term:artifact-version

## term:artifact-version
- kind: term
- dev: A monotonic logical version of a contract-entry path, minted each time a step produces that path. The taint model tracks taint per-version: clearing taint (via `sanitized-input:`) only affects the version visible at that step's position in the dependency graph. A later `produces:` of the same path creates a new version that is initially tainted if the producing step is a taint source or receives tainted inputs.
- pm: A way to track that the same file can be written multiple times with different trust levels. If step 5 cleans a file and step 7 re-downloads it from an untrusted source, step 7 creates a new "version" of the file that is untrusted again — even though step 5 cleaned an earlier version.
- related: term:taint, term:sanitized-input

## unsupported-spec-version
- kind: finding
- dev: Spec frontmatter is missing or carries a non-1.0 version. Tier-1 block. Hard cutover from v0.9 — no version-dispatch logic, no migration tool.
- pm: This spec uses a version Spectre no longer supports. Re-run /vision to regenerate it as a v1.0 spec.
- triggered_by: Tier-1 spec_ast classify; spec frontmatter check.
- user_action: Re-run /vision to regenerate the spec at v1.0.
- related: term:view
- since: v1.0

## missing-view-section
- kind: finding
- dev: One of §§9-13 is absent from a v1.0 spec. Tier-1 block. Each view must be present (with content) or explicitly marked `not-applicable`.
- pm: A required perspective section is missing from this spec. Either fill it in or declare it not applicable.
- triggered_by: Tier-1 spec_ast classify when scanning §§9-13.
- user_action: Add the missing section per the v1.0 template, or mark the view not-applicable in its §8.x substrate block.
- related: missing-substrate-block, malformed-view-contract
- since: v1.0

## missing-substrate-block
- kind: finding
- dev: One of §§8.3-8.7 is absent from a v1.0 spec. Tier-1 block. Each receiver-calibration block must be present.
- pm: A required receiver-calibration block is missing. Add it (or mark the view not-applicable).
- triggered_by: Tier-1 spec_ast classify when scanning §§8.3-8.7.
- user_action: Add the missing ### 8.x substrate block per the v1.0 template.
- related: missing-view-section
- since: v1.0

## excessive-not-applicable
- kind: finding
- dev: More than two of the five non-agent views are marked not-applicable. Tier-1 warn. Likely the spec is under-specified rather than legitimately narrow-scope.
- pm: This spec marks three or more views as not-applicable. That usually means something was overlooked rather than legitimately out of scope.
- triggered_by: Tier-1 v1.0 structural check.
- user_action: Review each N/A view — is it legitimately out of scope, or have you skipped a propagation event the spec should address?
- related: term:view
- since: v1.0

## malformed-view-contract
- kind: finding
- dev: A view section (§§9-13) declares neither Mechanical contracts, Coverage contracts, nor Exemplar bindings subsections. Tier-1 block.
- pm: A view section is empty — no contracts declared. Either add contracts or mark the view not-applicable.
- triggered_by: Tier-1 v1.0 structural check.
- user_action: Add at least one of `### Mechanical contracts`, `### Coverage contracts`, or `### Exemplar bindings` to the view, or mark the view not-applicable in its §8.x block.
- related: missing-view-section
- since: v1.0

## cross-view-string-unresolved
- kind: finding
- dev: A §§9-13 reference like `<halt-hint from §8.2 ux-contract>` names a field that doesn't exist in the referenced substrate block. Tier-2 block.
- pm: A view section references a field from another section that isn't there. Fix the reference or add the missing field.
- triggered_by: Tier-2 cross_view_gate.
- user_action: Add the named field to the referenced §8.x block, or change the reference to a field that exists.
- related: term:view
- since: v1.0

## exemplar-not-found
- kind: finding
- dev: A spec binds to `exemplar:<key>` but no entry by that key exists in the plugin catalog (`docs/exemplars/`) or user overlay (`~/.spectre/exemplars/`). Tier-2 block.
- pm: This spec names an exemplar that isn't in the catalog. Run `spectre exemplars list` to see valid options.
- triggered_by: Tier-2 cross_view_gate.
- user_action: Run `spectre exemplars list` to find valid slugs, or author a new exemplar at `~/.spectre/exemplars/<view-type>/<slug>.md`.
- related: term:exemplar, exemplar-taxonomy-mismatch
- since: v1.0

## exemplar-taxonomy-mismatch
- kind: finding
- dev: A spec binds to an exemplar whose taxonomy-version differs from the version pinned in the spec. Tier-2 block.
- pm: This spec was locked against an older version of the design-choice list than the exemplar uses. Re-run /vision for the affected view, or pick an exemplar at the pinned version.
- triggered_by: Tier-2 cross_view_gate.
- user_action: Run `spectre catalog upgrade-taxonomy --spec <slug> --to <version>` to re-bind (re-runs the walker for the affected view), or pick a different exemplar.
- related: term:taxonomy-version, term:exemplar
- since: v1.0

## view-fingerprint-contradicts-hard-contract
- kind: finding
- dev: A §8.x receiver-fingerprint is inconsistent with §8.1 hard contract (e.g. §8.5 declares gui-only human-user but §8.1 mutates includes stdout/stderr/tty). Tier-2 block.
- pm: This spec's hard contract contradicts what one of its views claims. For example, declaring a graphical UI but allowing terminal-only output. Fix the contradiction in either section.
- triggered_by: Tier-2 cross_view_gate.
- user_action: Either change the §8.x receiver-fingerprint to match what §8.1 allows, or change §8.1 mutates/never-touches to match the view's fingerprint.
- related: term:view
- since: v1.0

## view-fingerprint-contradicts-exemplar-binding
- kind: finding
- dev: A view binds to an exemplar whose `calibrated-for` set doesn't include the view's §8.x receiver-fingerprint (e.g. §8.5 fingerprint `gui-only` bound to a `help-text:gh` exemplar calibrated for `[cli-power-user, cli-novice]`). Tier-2 warn. Empty `calibrated-for` = any-match escape hatch.
- pm: This view binds to an example whose audience doesn't match the view's audience. For instance, declaring a graphical interface but borrowing conventions from a command-line tool. Pick a different exemplar or update its `calibrated-for` set.
- triggered_by: Tier-2 cross_view_gate.
- user_action: Re-run `/vision` and pick an exemplar whose `calibrated-for` matches the view's fingerprint; or, if the catalog has no compatible exemplar, declare the binding as `post-ship-iteration`.
- related: view-fingerprint-contradicts-hard-contract, post-ship-iteration-deferral
- since: v1.1

## post-ship-iteration-deferral
- kind: finding
- dev: Operator picked the `post-ship-iteration` sentinel for a view's exemplar binding because no shipped exemplar matched the view's fingerprint. Tier-2 info — not a bug, signals catalog gap to be filled post-ship.
- pm: One of this spec's views has no example to follow in the catalog, so the operator deferred picking one until after shipping. Acceptable signal; not a defect.
- triggered_by: Tier-2 cross_view_gate when `<aspect>-style: post-ship-iteration` appears in a view section.
- user_action: None for ship. Post-ship, contribute a new exemplar to the catalog that matches this view's fingerprint, then re-bind.
- related: excessive-post-ship-iteration, view-fingerprint-contradicts-exemplar-binding
- since: v1.1

## excessive-post-ship-iteration
- kind: finding
- dev: More than one view in the same spec is bound to the `post-ship-iteration` sentinel. Tier-2 warn — signals a structural catalog gap (not just an individual mismatch).
- pm: This spec has multiple views with no matching examples in the catalog. The catalog likely has a structural gap that should be filled before more specs of this shape ship.
- triggered_by: Tier-2 cross_view_gate aggregator after counting `post-ship-iteration-deferral` findings.
- user_action: Audit which view types lack matching exemplars; contribute the missing exemplars to the catalog (or update existing exemplars' `calibrated-for` sets); re-run `/vision`.
- related: post-ship-iteration-deferral, view-fingerprint-contradicts-exemplar-binding
- since: v1.1

## view-coverage-overlap
- kind: finding
- dev: Two views' coverage contracts redundantly name the same content category. Tier-2 info — not a bug, but a hint the operator may want to consolidate.
- pm: Two of this spec's views ask for the same content category. Not wrong, but you may want to consolidate.
- triggered_by: Tier-2 cross_view_gate.
- user_action: Optionally consolidate the overlapping coverage requirement into one view, or leave as-is.
- related: term:view
- since: v1.0

## taxonomy-version-stale
- kind: finding
- dev: A spec pins a taxonomy version older than the catalog's current taxonomy for that view-type. Tier-1 warn. The spec can still evaluate against the pinned version, but new axes added post-lock are invisible to this spec.
- pm: This spec uses an older version of a design-choice list. It still works, but newer design choices added since you locked the spec won't apply unless you upgrade.
- triggered_by: Tier-1 v1.0 structural check.
- user_action: Run `spectre catalog upgrade-taxonomy --spec <slug> --to <version>` when you want to consider the newer axes, or ignore.
- related: term:taxonomy-version
- since: v1.0

## tier3-negative-paths-thin-coverage
- kind: finding
- dev: Emitted alongside any `negative-path-omission` finding whose step has fewer than 3 `negative-paths:` entries. No demotion is involved — `negative-path-omission` is info-severity and never enters the faithfulness demotion path. The pairing signals "the LLM judge flagged a missing failure branch AND the step's structural coverage is thin." Tier-3 warn, dismissable.
- pm: A step's failure-branch coverage is thin (fewer than 3 entries) and the automated review flagged a missing failure scenario. Consider adding more failure scenarios to the step's negative-paths section.
- triggered_by: Co-occurrence of a `negative-path-omission` finding (LLM-judge output) and `< 3` negative-paths entries on the affected step.
- user_action: Add more negative-paths entries to the flagged step (at least 3 entries covering different failure modes), or dismiss if the step genuinely has only one or two realistic failure branches.
- related: negative-path-omission
- since: v1.2

## walker.round
- kind: status
- dev: Emitted after each concern answer in the walker interview loop. Fields: round=N (1-based count of answered concerns), pending=K (remaining non-stale concerns). Provides per-round visibility into walk progress without exposing convergence decisions.
- pm: The walker just finished interview round N. There are K questions still to answer.
- triggered_by: walker.record_answer increments round_count.
- user_action: No action required. Monitor round and pending counts to gauge walk progress. Operator interpretation only — walker.round does not imply any threshold or convergence signal.
- related: walker.yield, walker.coverage
- since: v1.2
