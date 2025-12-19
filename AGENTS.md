# AGENTS

Last Updated: 2025-12-18 23:10:05

Nova batch processing
- Enable async batch mode by setting `BEDROCK_BATCH_ROLE_ARN`, `NOVA_BATCH_INPUT_PREFIX`, `NOVA_BATCH_OUTPUT_PREFIX` in `.env`.
- Batch submissions use Bedrock batch jobs; results are finalized when `/api/nova/status/<nova_job_id>` is polled.
- Batch cost estimates apply a 50% discount and are surfaced in the Nova UI.

Nova model keys
- Preview models are exposed as `pro_2_preview` (Nova 2 Pro) and `omni_2_preview` (Nova 2 Omni).
- Nova 2 Lite runtime calls require the inference profile `us.amazon.nova-2-lite-v1:0` while reporting uses `amazon.nova-2-lite-v1:0`.
- Nova pricing estimates are aligned to the latest published per-1K token rates in `NovaVideoService.MODEL_CONFIG`.

Database
- Run `migrations/003_add_nova_batch_fields.sql` to add batch metadata fields to `nova_jobs`.
