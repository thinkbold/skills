# Guided Case Intake

Use this intake only when `CASE_DIR/case-manifest.json` does not exist. Ask in
the user's language and in compact batches. Do not open application evidence
until the generated manifest passes preflight.

## Safety Rules

- First confirm that the case directory is approved controlled storage. If it
  is not, stop without collecting or writing case details.
- Ask only for facts needed by `assets/case-intake.template.json`. Never ask
  for protected characteristics, a SIN, birth date, health or accommodation
  details, immigration or citizenship information, family status, beliefs, or
  lifestyle information.
- Use non-sensitive stable labels such as `applicant-a`; do not put applicant
  names, email addresses, or phone numbers in `case_id` or `applicant_id`.
- Do not infer a confirmation. Every Boolean answer must be an explicit yes or
  no. Clarify missing or invalid answers before running the initializer.
- After controlled storage is confirmed, directory filenames may be listed to
  help the user map files, but file contents must remain unopened until
  preflight succeeds.
- Write the completed intake JSON only inside the controlled case directory,
  preferably as `work/case-intake.json`.

## Questions

Ask the scope and privacy gate first:

1. Is this exactly one ordinary market-rate residential rental application
   for a property in Ontario, Canada, rather than RGI/social housing or a
   commercial tenancy?
2. Will an applicant share a kitchen or bathroom with the owner or the owner's
   family? A yes is outside this skill.
3. Is this case folder approved controlled storage for applicant information?
4. Who is the privacy-responsible operator, and is there a confirmed process
   for applicant access and correction requests?

Stop if the case is out of scope, storage is not controlled, or the
access/correction process is not confirmed. Otherwise ask:

5. What non-sensitive `case_id` should identify this case?
6. What are the rental property's address, proposed monthly rent in CAD,
   expected lease start date (`YYYY-MM-DD`), and positive term in months?
7. Which applicants will sign this lease? For each signer, provide a stable
   non-name `applicant_id` and each case-relative file path and kind. Do not
   include a non-signing guarantor as an applicant.
8. Is the current counsel-approved general authorization available? If yes,
   provide its exact version, signing date (`YYYY-MM-DD`), and whether it
   discloses open-web checks. If no, record `available: false`; initialization
   may continue, but preflight must block evidence access.
9. Separately for Facebook and LinkedIn, is consent `not_requested`, `granted`,
   `refused`, or `withdrawn`? Never treat one platform's consent as consent for
   the other.
10. Is the case under a legal hold? Require an explicit yes or no.

Summarize the answers and ask the user to correct any factual error before
writing the intake file. This confirmation is about transcription accuracy; it
does not replace any required applicant authorization.

## Create the Manifest

Populate the same fields as `assets/case-intake.template.json`, then run:

```bash
PYTHONPATH=SKILL_DIR python3 SKILL_DIR/scripts/init_case.py CASE_DIR \
  --answers CASE_DIR/work/case-intake.json
```

Replace `SKILL_DIR` and `CASE_DIR` with actual paths or equivalent safely
quoted runtime variables. The initializer validates scope, privacy, dates,
rent, signing applicants, file paths, file types, and consent states. It creates
`inputs/`, `work/`, and `outputs/` when needed and writes
`case-manifest.json` exclusively.

Never overwrite or silently edit an existing `case-manifest.json`. If it
already exists, stop initialization and run preflight against that file. After
successful initialization, immediately run `scripts/validate_case.py CASE_DIR`
and do not open evidence unless `outputs/preflight.json` says
`can_extract: true`.
