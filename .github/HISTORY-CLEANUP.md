# One-time public history cleanup

On 17 October 2026, existing own data and Git history in the public Dinext repositories were anonymized. Own historical user metadata uses Administrator. Inherited upstream authors, data and licenses were preserved. Private Docs and Control Center were excluded.

This was a one-time operation. There are no ongoing checks for personal data and no new requirements for author identities or exported metadata in future changes. Normal application tests and repository checks continue to run.

Before resuming from a working copy created before this history replacement, create a fresh clone and reapply unfinished changes as a reviewed patch. Merging old history would undo the completed replacement. Keep recovery originals private.

GitHub account actors, old pull-request refs and cached commit views are separate platform limits. The historical cleanup does not rename platform accounts.
