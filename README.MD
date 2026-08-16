# School Submission Tracker API

A serverless AWS REST API that helps Education Management Information System (EMIS) officers track school data submissions efficiently — comparing submitted schools list against a master list in seconds instead of 30+ minutes of manual checking.

## Problem Statement

EMIS officers collect data from 165+ schools via Google Forms. Manually checking which schools have submitted and which schools have not submitted (missing schools) their termly data is:

- Time-consuming (30+ minutes)
- Tedious and error-prone
- Difficult to identify who needs reminders

## The Manual Process Looked Like This

- Open Google Forms responses (hundreds of entries)
- Open master school list (165 schools)
- Manually check which schools submitted
- Create a list of missing schools
- Send reminders to those who haven't submitted

> **Time required**: 30-45 minutes per check
> **Frequency**: 3-4 times during each collection period
> **Annual time waste**: 25+ hours of tedious, error-prone work

## Solution — School Submission Tracker API

This API automates the entire process:

- ✅ Compares submitted schools against master list
- ✅ Identifies missing schools instantly
- ✅ Detects duplicate submissions automatically
- ✅ Calculates completion rates
- ✅ Provides actionable reports

> **Time required**: 2 seconds per check
> **Accuracy**: 100%, no counting errors
> **Annual time saved**: 25+ hours

### Key Features

- ✅ **Instant Comparison** — Compares 165+ schools in <2 seconds and returns missing schools
- ✅ **Duplicate Detection** — Identifies schools that submitted multiple times
- ✅ **Completion Rate Calculation** — Shows submission progress percentage
- ✅ **Smart Name Matching** — Handles case differences and formatting variations
- ✅ **Secure Authentication** — API keys stored in AWS Secrets Manager
- ✅ **Fail-Closed Security** — Returns 503 if Secrets Manager is unavailable
- ✅ **30-Day History Tracking** — Every submission check is automatically saved with a missing-schools summary, completion stats, and a timestamp for trend analysis.
- ✅ **Auto-Cleanup** — DynamoDB TTL automatically removes history records after 30 days
- ✅ **History Endpoint** — View recent submission checks, track patterns, and identify chronic late submitters
- ✅ **API Documentation** — Self-documenting HTML homepage
- ✅ **Cost-Effective** — Runs on AWS Free Tier (costs $0.41/month)

## Core API Functionality

The API has four endpoints:

1. `GET /`
   - **Description**: Displays the API HTML documentation page
   - **Authentication**: None required

2. `POST /check-submissions`
   - **Description**: Check which schools have submitted their termly data and identify schools that have not (missing schools), via a JSON payload.
   - **Content-Type**: `application/json`
   - **Authentication**: API key required (`x-api-key` header)

3. `POST /upload-csv`
   - **Description**: Same comparison as `/check-submissions`, but accepts a CSV file upload instead of a JSON payload.
   - **Content-Type**: `multipart/form-data`
   - **Authentication**: API key required (`x-api-key` header)

4. `GET /history`
   - **Description**: View recent submission checks from the last 30 days (`?limit=` query param, max 50)
   - **Authentication**: API key required (`x-api-key` header)

---

## Endpoints Reference

| Method | Path                  | Auth Required      | Description                                           |
| ------ | --------------------- | ------------------- | ------------------------------------------------------ |
| GET    | `/`                    | No                   | API documentation (HTML)                               |
| POST   | `/check-submissions`   | Yes (`x-api-key`)    | Compare master vs. submitted schools (JSON body)        |
| POST   | `/upload-csv`          | Yes (`x-api-key`)    | Compare master vs. submitted schools (CSV upload)        |
| GET    | `/history`             | Yes (`x-api-key`)    | View recent submission checks (last 30 days `?limit=` param, max 50)  |


### API Response includes

- Summary stats (completion rate, missing count, duplicates)
- Sorted list of missing schools
- Sorted list of submitted schools
- Duplicate submission details (if any)
- Suggested next steps (schools to follow up with)

## Response Status Codes

| Code | Meaning | When it occurs |
|------|---------|-----------------|
| `200` | Success | Request processed successfully |
| `400` | Bad Request | Missing/invalid fields in request body, empty CSV, or no schools found in the specified column |
| `401` | Unauthorized | No `x-api-key` header included in the request |
| `403` | Forbidden | `x-api-key` header present but the key is invalid |
| `404` | Not Found | Endpoint/path does not exist |
| `500` | Internal Server Error | Unexpected error while processing the CSV or JSON payload |
| `503` | Service Unavailable | API key configuration could not be loaded from Secrets Manager — see [Security](#security) |

**Input:**
- `master_schools` — all schools expected to submit
- `submitted_schools` — schools that actually submitted

**JSON format for `/check-submissions`:**

```json
{
  "master_schools": ["SCHOOL A", "SCHOOL B", "SCHOOL C"],
  "submitted_schools": ["SCHOOL A", "SCHOOL C"]
}
```

**CSV format for `/upload-csv`:**

```csv
Master Schools,Submitted Schools
SCHOOL A,SCHOOL A
SCHOOL B,
SCHOOL C,SCHOOL C
```
---

## Architecture

- **AWS Lambda** (Python 3.11) — core logic
- **API Gateway** — REST endpoint
- **AWS Secrets Manager** — API key storage
- **DynamoDB** — 30-day submission history (auto-expiring via TTL)
- **AWS SAM** — Infrastructure as code

## Security

This API uses a **fail-closed** authentication pattern: if the API key configuration cannot be loaded (e.g., Secrets Manager is unavailable), the API returns `503 Service Unavailable`.
For local development, the API also supports running without requiring API keys. `local-env.json` is included in this repo — pass it directly to `sam local start-api` with `DISABLE_AUTH` set to `"true"` to override the Secrets Manager check entirely for local testing, so you don't need a real secret configured just to run the API on your machine. See [Part 1: Local Testing](#part-1-local-testing-no-aws-deployment-needed) below for details.

## Cost

Only **$0.41/month** for Secrets Manager. Everything else runs on AWS Free Tier!

## Project Structure

```
.
├── src/
│   └── app.py                    # Lambda handler
├── scripts/
│   └── setup_local_table.py      # Creates + seeds DynamoDB Local table
├── docs/
│   └── images/                   # Screenshots for README
├── template.yaml                 # SAM/CloudFormation template
├── test-data.json                # Sample JSON payload for /check-submissions
├── test-data.csv                 # Sample CSV payload for /upload-csv
├── docker-compose.yml            # DynamoDB Local for offline testing
├── local-env.json                # Local testing config
├── .gitignore
└── README.md
```

---

## Prerequisites

- [AWS CLI](https://aws.amazon.com/cli/) installed and configured (`aws configure`)
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html) installed
- [Docker](https://www.docker.com/) installed and running (required for `sam local`)
- Python 3.11
- An AWS account with permissions to create Lambda, API Gateway, Secrets Manager, DynamoDB, and IAM resources

---

## Part 1: Local Testing (No AWS Deployment Needed)

You can run and test this API fully offline on your machine before touching AWS, using DynamoDB Local in a Docker container alongside `sam local` for the Lambda/API Gateway emulation.

### 1. Start DynamoDB Local

Your `docker-compose.yml` runs both DynamoDB Local and a browsable admin UI:

```bash
docker-compose up -d
```

Confirm both containers are running:

```bash
docker ps
```

### 2. Create and seed the table in DynamoDB Local

This is a separate, empty database from real AWS DynamoDB — creating the table via CloudFormation does not create it here. A setup script handles table creation and seeds one sample history record for you:

```bash
python scripts/setup_local_table.py
```

This will:

- Create the `SchoolSubmissionHistory` table (matching the schema in `template.yaml`)
- Seed one sample submission-check record
- List all tables currently in DynamoDB Local so you can confirm it worked

> If you're re-running this after the table already exists, the script detects that and skips creation without error.

Browse the table visually at `http://localhost:8001`.

### 3. Build and run

Always check your actual network name first — Docker Compose prefixes it with your project folder name, so it won't always match what's written in `docker-compose.yml` exactly. Getting this wrong is a common source of confusing connection errors, so make this a habit before every local session:

```bash
docker network ls
```

Look for a name like `<your-folder-name>_school-tracker-network` and copy it exactly.

Then build and start, using the network name you just confirmed:

```bash
sam build
sam local start-api --env-vars local-env.json --docker-network <your-confirmed-network-name>
```

This starts a local server, usually at `http://127.0.0.1:3000`.

The app auto-detects it's running locally via the `AWS_SAM_LOCAL` environment variable (set automatically by SAM CLI) and points DynamoDB at `http://dynamodb-local:8000` instead of real AWS.

### 4. Test with the sample data

Using the included `test_data.csv` or `test_data.json` for `/upload-csv` and `/check-submissions` respectively:

> **Tip:** It's best to save your test payload to an actual file rather than typing it inline — easier to reuse, avoids shell-quoting headaches, and is what the `-F` / `-d` flags below are designed for.

**CSV upload:**

```bash
curl -X POST http://localhost:3000/upload-csv -F "file=@test_data.csv"
```

**Expected result:** 18 master schools, 9 unique submissions, 9 missing, 1 duplicate warning (School E), 50% completion rate.

> Check the terminal logs — you should see `✓ Authentication disabled for local testing` confirming local testing works without an API key in Secrets Manager.

**JSON endpoint (backward compatible):**

```bash
curl -X POST http://localhost:3000/check-submissions \
  -H "Content-Type: application/json" \
  -d "@test-data.json"
```

**Expected result:** 18 master schools, 9 unique submissions, 9 missing, 1 duplicate warning (School E), 50% completion rate.

**View history:**

```bash
curl http://localhost:3000/history
```

**Test the home page:**

```bash
curl http://localhost:3000/
```

> Should return the HTML documentation page.

### 5. (Optional) Test locally WITH real authentication

You can test the real auth flow locally just by running `sam local start-api` **without** the `--env-vars` flag at all — no config file needed. As long as you have a real secret already created in AWS, authentication will work exactly as it does in production (Secrets Manager isn't mocked locally, so this calls the real AWS API).

#### How to create the secret in Secrets Manager

```bash
openssl rand -hex 16
```

Then create the secret (replace `YOUR-GENERATED-KEY` below with your generated one):

```bash
aws secretsmanager create-secret \
  --name school-tracker/api-keys \
  --secret-string '{"enabled":true,"api_keys":["YOUR-GENERATED-KEY"]}'
```

Run without `--env-vars`, and test with your real key:

```bash
sam local start-api --docker-network <your-confirmed-network-name>

curl -X POST http://localhost:3000/upload-csv \
  -H "x-api-key: YOUR-KEY" \
  -F "file=@test-data.csv"
```

> Check the terminal logs — you should see `✓ Loaded API key configuration from Secrets Manager` and `✓ Authenticated request with API key ...` confirming it authenticated against your real secret.

### 6. Verify the fail-closed security behavior

Point `SECRET_NAME` at a non-existent secret, or delete your test secret temporarily:

```bash
curl -X POST http://localhost:3000/upload-csv -F "file=@test_data.csv"
```

> This should return `503 Service Unavailable`, confirming that authentication cannot be bypassed if Secrets Manager becomes unavailable.

---

## Part 2: Deploying to AWS

### 1. Build the Application

```bash
sam build
```

### 2. Deploy (first time — guided)

```bash
sam deploy --guided
```

Answer the prompts:

- **Stack Name** `[sam-app]`: e.g. `school-submission-tracker-api`
- **AWS Region** `[us-east-1]`: e.g. `us-west-1`, or press Enter for the default
- **Parameter SecretName** `[school-tracker/api-keys]`: type the name of the secret you created
- *(Shows the resource changes to be deployed and requires a `y` to proceed)*
- **Confirm changes before deploy** `[y/N]`: `y`
- *(SAM needs permission to create roles to connect to the resources in your template)*
- **Allow SAM CLI IAM role creation** `[Y/n]`: `y`
- *(Preserves the state of previously provisioned resources if a deployment fails)*
- **Disable rollback** `[y/N]`: `n`
- **Save arguments to configuration file** `[Y/n]`: `y`
- **SAM configuration file** `[samconfig.toml]`: press Enter
- **SAM configuration environment** `[default]`: press Enter

### 3. Get your API URL

Your API URL is shown at the end of the `sam deploy` output. If you need to look it up again later, use the command below — **replace `YOUR-STACK-NAME` with the stack name you actually used** during `sam deploy --guided`:

```bash
aws cloudformation describe-stacks --stack-name YOUR-STACK-NAME
```

Check the `Outputs` section at the end for the API URL.

### 4. Test the deployed API

```bash
# Home page (no auth)
curl https://YOUR-API-URL/Prod/

# Check submissions (auth required)
curl -X POST https://YOUR-API-URL/Prod/check-submissions \
  -H "x-api-key: YOUR-KEY" \
  -H "Content-Type: application/json" \
  -d "@test-data.json"

# Upload CSV (auth required)
curl -X POST https://YOUR-API-URL/Prod/upload-csv \
  -H "x-api-key: YOUR-KEY" \
  -F "file=@test-data.csv"

# View history (auth required)
curl https://YOUR-API-URL/Prod/history \
  -H "x-api-key: YOUR-KEY"
```

### 5. Verify the fail-closed security behavior (optional)

```bash
# Should return 401 - no key provided
curl -X POST https://YOUR-API-URL/Prod/check-submissions \
  -H "Content-Type: application/json" \
  -d "@test-data.json"

# Should return 403 - wrong key
curl -X POST https://YOUR-API-URL/Prod/check-submissions \
  -H "x-api-key: wrong-key" \
  -H "Content-Type: application/json" \
  -d "@test-data.json"
```

---


## Cleaning Up

1. Remove all deployed AWS resources:

```bash
sam delete
```

2. Remove the secret (use the secret name you created):

```bash
aws secretsmanager delete-secret \
  --secret-id school-tracker/api-keys \
  --recovery-window-in-days 7
```

---

## Roadmap

- [x] v1: Secrets Manager, fail-closed auth
- [x] v2: CSV upload + DynamoDB 30-day history
- [ ] v2.1: Migrate to SSM Parameter Store (fully free tier)
- [ ] v3: SSE integration + web dashboard

---

## Contributing

This project was built to solve a real problem for EMIS officers in Ghana. If you're facing similar challenges, feel free to:

- Fork this repository
- Adapt it to your needs
- Submit issues or suggestions
- Share your use case

## Blog Post

Read the full story behind this project: [Building a Production Ready AWS Serverless API That Saves Me 25+ Hours Per Year](https://medium.com/@gloriaboakye/how-i-built-an-aws-api-to-automate-school-data-tracking-for-165-schools-and-saved-25-hours-per-d349803de953)

## License

MIT License - feel free to use this for your own EMIS data tracking needs!

## Author

Gloria Boakye — EMIS Officer, Ghana Education Service | AWS Community Builder (Serverless)