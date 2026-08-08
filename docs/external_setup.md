# External Setup — PlotPoints

This project depends on a handful of external services (TMDB, Snowflake, AWS S3) that
have to be provisioned manually before the pipeline will run. This doc walks through
provisioning all of them from scratch. Budget 30-45 minutes.

> **Moving machines / already provisioned?** If the services already exist and you just need the repo
> running on another machine, follow the **Setup** steps in the [README](../README.md) plus your `.env`
> and RSA key file — this runbook is only for first-time provisioning from scratch.

Copy `.env.example` to `.env` as you go and fill in values as each step produces them.
`.env` is gitignored — never commit it.

## Prerequisites

- A [TMDB](https://www.themoviedb.org/) account
- A [Snowflake](https://signup.snowflake.com/) trial account (30-day, $400 credit).
  Choose **AWS** as the cloud provider and a standard commercial region
  (`us-east-1` is a safe default).
- An [AWS](https://aws.amazon.com/) account (free tier is sufficient)
- Git Bash (ships with [Git for Windows](https://git-scm.com/download/win)) — needed
  later for key-pair generation, since it includes OpenSSL and plain PowerShell doesn't

## 1. TMDB

1. Create an account, then go to Settings → API and request a key (choose "Developer").
2. Set `TMDB_API_KEY` in `.env`.

## 2. Letterboxd

No account setup needed — the diary RSS feed is public. There's no `.env` entry for
this: pass your Letterboxd username to `fetch_diary.py` as an argument
(`uv run src/fetch_diary.py <username>`), or enter it when the script prompts.

## 3. Snowflake — core objects

Sign in to Snowsight, open a **SQL File** (Projects → Workspaces → + Add New → SQL File
— Snowflake renamed "Worksheets" to "Workspaces" in 2026), set the role selector to
**ACCOUNTADMIN**, and run:

```sql
USE ROLE ACCOUNTADMIN;

-- Warehouse: creates if missing, otherwise updates size/suspend settings in place
CREATE OR ALTER WAREHOUSE PLOTPOINTS_WH
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE;

-- Database
CREATE OR ALTER DATABASE PLOTPOINTS_DB;

-- Role
CREATE OR ALTER ROLE PLOTPOINTS_ROLE;

GRANT USAGE ON WAREHOUSE PLOTPOINTS_WH TO ROLE PLOTPOINTS_ROLE;
GRANT USAGE ON DATABASE PLOTPOINTS_DB TO ROLE PLOTPOINTS_ROLE;
GRANT ALL ON DATABASE PLOTPOINTS_DB TO ROLE PLOTPOINTS_ROLE;
GRANT CREATE SCHEMA ON DATABASE PLOTPOINTS_DB TO ROLE PLOTPOINTS_ROLE;

-- CREATE DATABASE auto-creates a PUBLIC schema, but GRANT ALL ON DATABASE above
-- doesn't cascade into it — it needs its own explicit grants.
GRANT USAGE ON SCHEMA PLOTPOINTS_DB.PUBLIC TO ROLE PLOTPOINTS_ROLE;
GRANT CREATE STAGE ON SCHEMA PLOTPOINTS_DB.PUBLIC TO ROLE PLOTPOINTS_ROLE;

-- Service user
CREATE USER IF NOT EXISTS PLOTPOINTS_SVC;
ALTER USER PLOTPOINTS_SVC SET
  DEFAULT_ROLE = PLOTPOINTS_ROLE
  DEFAULT_WAREHOUSE = PLOTPOINTS_WH;

GRANT ROLE PLOTPOINTS_ROLE TO USER PLOTPOINTS_SVC;
GRANT ROLE PLOTPOINTS_ROLE TO USER <your_snowsight_username>;

GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE PLOTPOINTS_ROLE;

-- Resource monitor (adjust CREDIT_QUOTA to your comfort level)
CREATE OR REPLACE RESOURCE MONITOR PLOTPOINTS_MONITOR
  WITH CREDIT_QUOTA = 25
  TRIGGERS
    ON 50 PERCENT DO NOTIFY
    ON 90 PERCENT DO SUSPEND
    ON 100 PERCENT DO SUSPEND_IMMEDIATE;
ALTER WAREHOUSE PLOTPOINTS_WH SET RESOURCE_MONITOR = PLOTPOINTS_MONITOR;
```

This script is idempotent — safe to re-run if you change a setting later.

**Verify:**
```sql
SHOW WAREHOUSES LIKE 'PLOTPOINTS_WH';
SHOW DATABASES LIKE 'PLOTPOINTS_DB';
SHOW ROLES LIKE 'PLOTPOINTS_ROLE';
DESC USER PLOTPOINTS_SVC;
SHOW RESOURCE MONITORS LIKE 'PLOTPOINTS_MONITOR';

-- Run this as PLOTPOINTS_ROLE (or PLOTPOINTS_SVC) specifically, not ACCOUNTADMIN —
-- it should list PUBLIC. If it only shows INFORMATION_SCHEMA, the
-- GRANT USAGE ON SCHEMA above didn't take.
SHOW SCHEMAS IN DATABASE PLOTPOINTS_DB;
```

Note your Snowflake **account identifier** now — click your username (bottom-left) →
Account, or read it from the browser URL (`https://<account_identifier>.snowflakecomputing.com`).
Set `SNOWFLAKE_ACCOUNT` in `.env`.

## 4. AWS — S3 bucket

S3 console → Create bucket:
- Name: something globally unique, e.g. `plotpoints-raw-<your-suffix>`
- Region: match your Snowflake region (`us-east-1`)
- Block all public access: on (default)
- Everything else: defaults are fine

Set `AWS_S3_BUCKET` and `AWS_REGION` in `.env`.

## 5. AWS — uploader IAM user (write-only, for local scripts)

IAM → Policies → Create policy → JSON tab:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": "s3:ListBucket", "Resource": "arn:aws:s3:::<bucket>"},
    {"Effect": "Allow", "Action": "s3:PutObject", "Resource": "arn:aws:s3:::<bucket>/*"}
  ]
}
```
Name it `plotpoints-uploader-policy`.

IAM → Users → Create user → `plotpoints-uploader` → programmatic access only → attach
the policy directly. After creation, go to the user → Security credentials → Create
access key → "Application running outside AWS". Download the CSV, copy the two values
into `.env` as `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`, then delete the CSV —
it's a plaintext copy of a live secret.

## 6. AWS — IAM role for Snowflake (read-only, used by the storage integration)

IAM → Policies → Create policy → JSON tab:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": ["s3:GetObject", "s3:GetObjectVersion"], "Resource": "arn:aws:s3:::<bucket>/*"},
    {"Effect": "Allow", "Action": "s3:ListBucket", "Resource": "arn:aws:s3:::<bucket>"}
  ]
}
```
Name it `plotpoints-snowflake-policy`.

IAM → Roles → Create role → Custom trust policy, paste this placeholder (swap in your
12-digit AWS account ID, shown top-right in the console):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::<your_aws_account_id>:root"},
      "Action": "sts:AssumeRole",
      "Condition": {"StringEquals": {"sts:ExternalId": "0000"}}
    }
  ]
}
```
Attach `plotpoints-snowflake-policy`, name the role `plotpoints-snowflake-role`, and
copy its Role ARN.

## 7. Snowflake — storage integration

Back in a SQL File:
```sql
CREATE STORAGE INTEGRATION plotpoints_s3_int
  TYPE = EXTERNAL_STAGE
  STORAGE_PROVIDER = 'S3'
  ENABLED = TRUE
  STORAGE_AWS_ROLE_ARN = '<plotpoints-snowflake-role ARN from step 6>'
  STORAGE_ALLOWED_LOCATIONS = ('s3://<bucket>/');

DESC STORAGE INTEGRATION plotpoints_s3_int;
```
From the `DESC` output, copy the `STORAGE_AWS_IAM_USER_ARN` and `STORAGE_AWS_EXTERNAL_ID`
values.

## 8. AWS — close the trust loop

IAM → Roles → `plotpoints-snowflake-role` → Trust relationships → Edit trust policy →
replace the placeholder with the real values from step 7:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"AWS": "<STORAGE_AWS_IAM_USER_ARN>"},
      "Action": "sts:AssumeRole",
      "Condition": {"StringEquals": {"sts:ExternalId": "<STORAGE_AWS_EXTERNAL_ID>"}}
    }
  ]
}
```
Save it, then back in Snowflake:
```sql
GRANT USAGE ON INTEGRATION plotpoints_s3_int TO ROLE PLOTPOINTS_ROLE;
```
**Verify:** `DESC STORAGE INTEGRATION plotpoints_s3_int;` should show `ENABLED = true`
with no error state.

## 9. Key-pair authentication

In Git Bash:
```bash
cd ~
mkdir -p .snowflake/plotpoints
cd .snowflake/plotpoints
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt
openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub
cat rsa_key.pub
```
Copy everything between the `-----BEGIN PUBLIC KEY-----` and `-----END PUBLIC KEY-----`
lines (not those header/footer lines themselves) as one continuous string.

In a SQL File:
```sql
ALTER USER PLOTPOINTS_SVC SET RSA_PUBLIC_KEY='<paste key body>';
```

**Verify:** `DESC USER PLOTPOINTS_SVC;` — `RSA_PUBLIC_KEY_FP` should show a
`SHA256:...` fingerprint, not blank.

Set `SNOWFLAKE_PRIVATE_KEY_PATH` in `.env` to the absolute path of `rsa_key.p8`
(e.g. `/c/Users/<you>/.snowflake/plotpoints/rsa_key.p8` in Git Bash form, or the
Windows path your connector library expects). Leave
`SNOWFLAKE_PRIVATE_KEY_PASSPHRASE` blank, since the key above was generated without one.

## Done

At this point `.env` should be fully populated and every account/resource above should
exist and pass its verification step. The application code itself (Snowflake connector,
external stage creation, load scripts) is built separately — see the main README for
pipeline usage.