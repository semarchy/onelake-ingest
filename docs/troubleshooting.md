# Troubleshooting

`scripts/run_pipeline.py` prints every step of a run with its error message; the pipeline's run
history in Fabric shows the same. Find the step that failed, then the symptom below.

| Symptom | Cause and fix |
|---|---|
| Creating a connection: "The credentials provided for the AzurePostgreSQL source are invalid" | Usually the **server**, not the password: a login that does not exist on that server fails the same way. Check you have the data location's server for `hub` and the repository's for `repo`. |
| `relation "mta_data_location" does not exist` in GetLoadId | `fabric_loader`'s search_path lacks the repository schema. Re-run `sql/01_create_loader_role.sql` on the repository database with `-v repo_schema`. |
| `permission denied to create role` | `sql/01_create_loader_role.sql` was run by a role without CREATEROLE. Run it as the server admin. |
| `No Integration Job named ...` in SubmitLoad | Wrong `integrationJob` in the environment file; see [Collect the values](setup-guide.md#1-collect-the-values). |
| Batch ends `WARNING` | Normal: warning-level validations fired on some records. The run succeeds and the watermark advances. |
| Batch ends `SUSPENDED` | Needs a person: the data location's integration queue is stopped until the batch is resolved in SDP. The watermark does not move, so the rows are retried after that. |
| A deployment of the data location fails with HTTP 500 | Look for a `RUNNING` load. The pipeline cancels its own on failure; a load from an interrupted run may need cancelling in SDP. |
| A run copies 0 rows right after new data was written | The Lakehouse SQL analytics endpoint reflects writes after a short delay. The next run picks the rows up. |
| `unresolved tokens in the template` on deploy | The template uses a token the renderer does not fill in; see [Changing the pipeline](how-it-works.md#changing-the-pipeline). |
| An environment file is rejected for a quote character | A schema, table, column or name the pipeline places inside SQL contains `"`, `'`, `[` or `]`. Rename it in the source or in SDP. |
