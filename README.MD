# School Submission Tracker API - VERSION 1

A serverless AWS REST API that helps Education Management Information System (EMIS) officers track school data submissions efficiently — comparing submitted schools list against a master list in seconds instead of 30+ minutes of manual checking.

## Problem Statement
EMIS officers collect data from 165+ schools via Google Forms. Manually checking which schools have submitted and which schools have not submitted(missing schools) their termly data is:

* Time-consuming (30+ minutes)
* Tedious and error-prone
* Difficult to identify who needs reminders

## The manual process looked like this:

* Open Google Forms responses (hundreds of entries)
* Open my master school list (165 schools)
* Manually check which schools submitted
* Create a list of missing schools
* Send reminders to those who haven't submitted


>- **Time required**: 30-45 minutes per checK  **Frequency**: 3-4 times during each collection period **Annual time waste**: 25+ hours of tedious, error-prone work

## Solution - School Submission Tracker API
This API automates the entire process:

- ✅ Compares submitted schools against master list
- ✅ Identifies missing schools instantly
- ✅ Detects duplicate submissions automatically
- ✅ Calculates completion rates
- ✅ Provides actionable reports

>**Time required**: 2 sceconds per check
**Accuracy**: 100%, no counting errors
**Annual time saved**: 25+ hours 

Key Features:
- ✅ Instant Comparison — Compares 165+ schools in <2 seconds and returns missing schools
- ✅ Duplicate Detection — Identifies schools that submitted multiple times
- ✅ Completion Rate Calculation — Shows submission progress percentage
- ✅ Smart Name Matching — Handles case differences, and formatting variations
- ✅ Secure Authentication — API keys stored in AWS Secrets Manager
- ✅ API Documentation — Self documenting HTML homepage 
- ✅ Cost-Effective — Runs on AWS free tier (costs $0.41/month)

## Core API Functionality
The API has two main endpoints:

1. `GET /` :
- **Description**: Displays the API HTML documentation page
- **Authentication**: None required

2. `POST /check-submissions` :
- **Description**: Check which schools have submitted their termly data and identify school that have not (missing schools)
- **Authentication**: API key required (x-api-key header)

** Input
*master_schools (all schools expected to submit)
*submitted_schools (schools that actually submitted)

## Architecture

- **AWS Lambda** (Python 3.11) — core logic
- **API Gateway** — REST endpoint
- **AWS Secrets Manager** — API key storage
- **AWS SAM** — Infrastructure as code

## Security

This API uses a **fail-closed** authentication pattern: if the API key configuration cannot be loaded (e.g., Secrets Manager is unavailable), the API returns`503 Service Unavailable`.

For local development, the API also supports running without requiring API keys.
`local-env.json` is included in this repo — pass it directly to
`sam local start-api` with DISABLE_AUTH set to "true" to override the Secrets Manager check entirely for local testing, so you don't need a real secret configured just to run the API on your machine. See [Part 1: Local Testing](#part-1-local-testing-no-aws-deployment-needed) below for details.

## Cost
Only **$0.41/month** for Secrets Manager. Everything else runs on AWS Free Tier!

## Project Structure
```
.
├── src/
│   └── app.py                     # Lambda handler
├── docs/
│   └── images/                    # Screenshots 
├── template.yaml                  # SAM/CloudFormation template
├── test_data.json                 # Sample request payload for testing
├── local-env.json                 # Local testing config
├── .gitignore
└── README.md
````

---

## Prerequisites

- [AWS CLI](https://aws.amazon.com/cli/) installed and configured (`aws configure`)
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html) installed
- [Docker](https://www.docker.com/) installed and running (required for `sam local`)
- Python 3.11
- An AWS account with permissions to create Lambda, API Gateway, Secrets Manager, and IAM resources

---

## Part 1: Local Testing (No AWS Deployment Needed)

You can run and test this API entirely on your machine before touching AWS.

### 1. Build the application

```bash
sam build
```

### 2. Run locally with authentication disabled

For quick local testing, skip the Secrets Manager check entirely:

```bash
sam local start-api --env-vars local-env.json
```

This starts a local server, usually at `http://127.0.0.1:3000`.

### 3. Test with the sample data

Using the included `test_data.json`:

```bash
curl -X POST http://127.0.0.1:3000/check-submissions \
  -H "Content-Type: application/json" \
  -d "@test_data.json"
```

**Expected result:** 18 master schools, 9 unique submissions, 9 missing, 1 duplicate warning (School E).

>Check the terminal logs: you should see Authentication disabled for local testing confirming local testing works without api keys in secret manager


### 4. Test the home page

```bash
curl http://127.0.0.1:3000/
```

- Should return the HTML documentation page.

### 5. (Optional) Test locally WITH real authentication

Since `DISABLE_AUTH` defaults to `"false"` in `template.yaml`, you can test the real
auth flow locally just by running `sam local start-api` **without** the `--env-vars` flag at all — no config file needed. As long as you have a real secret already created in AWS, authentication will work exactly as it does in production (Secrets Manager isn't mocked locally, so this calls the real AWS API).

#### How to create the secret in Secrets Manager

```bash
openssl rand -hex 16
```

Then create the secret (replace `YOUR-GENERATED-KEY` in the code below with your generated one):

```bash
aws secretsmanager create-secret \
  --name school-tracker/api-keys \
  --secret-string '{"enabled":true,"api_keys":["YOUR-GENERATED-KEY"]}'
```

### 6. Run locally with authentication enabled
```bash
sam local start-api
```
### 7. Test endpoints
```
curl -X POST http://127.0.0.1:3000/check-submissions \
  -H "x-api-key: YOUR-KEY" \
  -H "Content-Type: application/json" \
  -d "@test_data.json"
```
**Expected result:** 18 master schools, 9 unique submissions, 9 missing, 1 duplicate warning (School E).

>Check the terminal logs — you should see `✓ Successfully loaded API keys from
Secrets Manager` and `✓ Authenticated request with API key: ...` confirming it
authenticated against your real secret.

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

- Stack Name [sam-app]: e.g. `school-submission-tracker-api`
- AWS Region [us-east-1]: e.g. `us-west-1 or press enter to default to us-east-1`
- Parameter SecretName [school-tracker/api-keys] : `type the name of the secret you created`
- #Shows you resources changes to be deployed and require a 'Y' to initiate deploy
- Confirm changes before deploy [y/N]: `y`
- SAM needs permission to be able to create roles to connect to the resources in your template
- Allow SAM CLI IAM role creation [Y/n]: `y`
- #Preserves the state of previously provisioned resources when an operation fails
- Disable rollback [y/N]: `n`
- Save arguments to configuration file [Y/n]: `y`
- SAM configuration file [samconfig.toml]: `press enter`
- SAM configuration environment [default]: `press enter`



### 3. Get your API URL from the deployment output or from the command line
Your API URL is shown at the end of the `sam deploy` output. If you need to look it up again later, use the command below 
- **make sure to replace the stack name with the one you actually used** during `sam deploy --guided`:

```bash
aws cloudformation describe-stacks --stack-name YOUR-STACK-NAME
```
- check the output at the end for the API URL

### 4. Test the deployed API

```bash
# Home page (no auth)
curl https://YOUR-API-URL/Prod/

# Check submissions (auth required)
curl -X POST https://YOUR-API-URL/Prod/check-submissions \
  -H "x-api-key: YOUR-KEY" \
  -H "Content-Type: application/json" \
  -d "@test_data.json"
```

### 5. Verify the fail-closed security behavior (optional)

```bash
# Should return 401 - no key provided
curl -X POST https://YOUR-API-URL/Prod/check-submissions \
  -H "Content-Type: application/json" \
  -d "@test_data.json"

# Should return 403 - wrong key
curl -X POST https://YOUR-API-URL/Prod/check-submissions \
  -H "x-api-key: wrong-key" \
  -H "Content-Type: application/json" \
  -d "@test_data.json"
```

---


## Cleaning Up

1. Remove all deployed AWS resources:

```bash
sam delete
```

2. Then remove the secret:
Make sure to use the secret name you created

```bash
aws secretsmanager delete-secret \
  --secret-id school-tracker/api-keys \
  --recovery-window-in-days 7
```

---

## Endpoints Reference

| Method | Path | Auth Required | Description |
|--------|------|----------------|-------------|
| GET | `/` | No | API documentation (HTML) |
| POST | `/check-submissions` | Yes (`x-api-key`) | Compare master vs. submitted schools |

### Request format for `/check-submissions`

```json
{
  "master_schools": ["SCHOOL A", "SCHOOL B", "SCHOOL C"],
  "submitted_schools": ["SCHOOL A", "SCHOOL C"]
}
```

### Response includes

- Summary stats (completion rate, missing count, duplicates)
- Sorted list of missing schools
- Sorted list of submitted schools
- Duplicate submission details (if any)
- Suggested next steps (schools to follow up with)

---
## Roadmap

- [ Phase 2: DynamoDB integration for historical tracking](https://medium.com/@gloriaboakye/adding-file-uploads-30-day-history-to-my-school-tracker-api-f8972d49a501) 
- [ ] Phase 3 - Coming Soon: Email reminder automation
- [ ] Phase 3 -Coming soon: Web dashboard interface
- [ ] Phase 4: Direct Google Forms API integration

## Contributing

This project was built to solve a real problem for EMIS officers in Ghana. If you're facing similar challenges, feel free to:

- Fork this repository
- Adapt it to your needs
- Submit issues or suggestions
- Share your use case

## Blog Post

Read the full story behind this project:[Building a Production Ready AWS Serverless API That Saves Me 25+ Hours Per Year](https://medium.com/@gloriaboakye/how-i-built-an-aws-api-to-automate-school-data-tracking-for-165-schools-and-saved-25-hours-per-d349803de953)

## License

MIT License - feel free to use this for your own EMIS data tracking needs!

## Author

Gloria Boakye — EMIS Officer, Ghana Education Service | AWS Community Builder (Serverless)