# AWS IAM Setup for Nova Integration

## Required Permissions

To enable AWS Nova integration, you need to add the following permissions to your IAM user or role.

### Step 1: Access AWS IAM Console

1. Log into AWS Console: https://console.aws.amazon.com/
2. Navigate to IAM (Identity and Access Management)
3. Find your current IAM user/role: `video-analysis-app`

### Step 2: Add Nova Permissions

You have two options:

#### Option A: Update Existing Policy (Recommended)

1. Go to **Policies** in IAM
2. Find your existing policy: `VideoAnalysisAppPolicy`
3. Click **Edit policy**
4. Switch to **JSON** tab
5. Add the following statements to the existing policy:

```json
{
  "Sid": "BedrockNovaModelInvocation",
  "Effect": "Allow",
  "Action": [
    "bedrock:InvokeModel",
    "bedrock:InvokeModelWithResponseStream"
  ],
  "Resource": [
    "arn:aws:bedrock:us-east-1::foundation-model/us.amazon.nova-micro-v1:0",
    "arn:aws:bedrock:us-east-1::foundation-model/us.amazon.nova-lite-v1:0",
    "arn:aws:bedrock:us-east-1::foundation-model/us.amazon.nova-pro-v1:0",
    "arn:aws:bedrock:us-east-1::foundation-model/us.amazon.nova-pro-v2:0",
    "arn:aws:bedrock:us-east-1::foundation-model/us.amazon.nova-omni-v2:0",
    "arn:aws:bedrock:us-east-1::foundation-model/us.amazon.nova-premier-v1:0"
  ]
},
{
  "Sid": "BedrockModelDiscovery",
  "Effect": "Allow",
  "Action": [
    "bedrock:GetFoundationModel",
    "bedrock:ListFoundationModels"
  ],
  "Resource": "*"
}
```

6. Click **Review policy**
7. Click **Save changes**

#### Option B: Create Separate Nova Policy

1. Go to **Policies** in IAM
2. Click **Create policy**
3. Switch to **JSON** tab
4. Paste the complete policy from `docs/IAM_POLICY_NOVA.json`
5. Name it: `NovaVideoAnalysisPolicy`
6. Click **Create policy**
7. Attach the new policy to your IAM user/role

### Step 2.5: Batch Mode Permissions (Optional)

If you plan to use Nova Batch mode (50% cost reduction, async), add these permissions:

```json
{
  "Sid": "BedrockBatchInference",
  "Effect": "Allow",
  "Action": [
    "bedrock:CreateModelInvocationJob",
    "bedrock:GetModelInvocationJob",
    "bedrock:ListModelInvocationJobs",
    "bedrock:StopModelInvocationJob"
  ],
  "Resource": "*"
},
{
  "Sid": "IAMPassRoleForBatch",
  "Effect": "Allow",
  "Action": "iam:PassRole",
  "Resource": "arn:aws:iam::123456789012:role/BedrockBatchRole"
}
```

Also ensure the batch role has S3 read/write to the Nova batch input/output prefixes.

### Step 3: Enable Bedrock Model Access

**IMPORTANT**: You may need to request access to Nova models in Amazon Bedrock.

1. Go to Amazon Bedrock Console: https://console.aws.amazon.com/bedrock/
2. Navigate to **Model access** (left sidebar)
3. Click **Manage model access**
4. Check the boxes for:
   - Amazon Nova Micro
   - Amazon Nova Lite
   - Amazon Nova Pro
   - Amazon Nova Premier (if available)
5. Click **Request model access** or **Save changes**

**Note**: Some models may require approval. Nova Micro and Lite should be available immediately.

### Step 4: Verify Access

You can verify your IAM permissions using AWS CLI:

```bash
# Test Bedrock access
aws bedrock list-foundation-models --region us-east-1

# Test S3 access (already configured)
aws s3 ls s3://video-analysis-app-676206912644/
```

If you see model information returned, you're good to go!

### Step 5: Update Application (if needed)

No changes needed to `.env` file - the existing AWS credentials will work with Bedrock Nova as long as IAM permissions are correct.

### Troubleshooting

**Error: AccessDeniedException when invoking Nova**
- Solution: Ensure IAM policy includes `bedrock:InvokeModel` action for Nova model ARNs
- Check that model ARN is correct for your region (us-east-1)

**Error: ModelAccessDeniedException**
- Solution: Go to Bedrock console and request model access (Step 3 above)
- Wait a few minutes for access to be granted

**Error: ValidationException - Invalid model ID**
- Solution: Double-check model ID format: `us.amazon.nova-lite-v1:0`
- Ensure you're using the correct region (us-east-1)

### Cost Considerations

- Nova Micro: $0.035 per 1K input tokens
- Nova Lite: $0.06 per 1K input tokens
- Nova Pro: $0.80 per 1K input tokens
- Nova Premier: ~$2.00 per 1K input tokens (estimated)

For a 5-minute video, expect:
- Micro: $0.01-$0.05
- Lite: $0.02-$0.10 (recommended default)
- Pro: $0.05-$0.15

### Security Best Practices

1. ✅ Use IAM policies with least privilege (specific model ARNs)
2. ✅ Enable AWS CloudTrail for audit logging
3. ✅ Set up AWS Budgets alerts for cost monitoring
4. ✅ Rotate IAM access keys regularly
5. ✅ Never commit `.env` file to git (already in .gitignore)

---

## Current IAM Status

- [x] S3 Access: Configured ✅
- [x] Rekognition Access: Configured ✅
- [ ] Bedrock Nova Access: **Needs to be added** ⚠️

Once you complete the steps above, check this box in NOVA_PROGRESS.md:
- [ ] Phase 1.1: Set up IAM permissions for Bedrock Nova access
