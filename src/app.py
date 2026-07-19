import json
import csv
import io
import datetime
import os
import boto3
import uuid
import base64
from botocore.exceptions import ClientError
from collections import Counter
from decimal import Decimal

# Initialize AWS clients
secrets_client = boto3.client('secretsmanager')

# For local testing, use DynamoDB Local endpoint
is_sam_local = os.environ.get('AWS_SAM_LOCAL') == 'true'

if is_sam_local:
    # Force DynamoDB Local when running in SAM
    HISTORY_TABLE_NAME = 'SchoolSubmissionHistory'  # Hardcode for local
    dynamodb_endpoint = 'http://dynamodb-local:8000'
    print(f"🔧 SAM Local detected - Using DynamoDB Local at: {dynamodb_endpoint}")
    dynamodb = boto3.resource('dynamodb', endpoint_url=dynamodb_endpoint)
else:
    HISTORY_TABLE_NAME = os.environ.get('HISTORY_TABLE_NAME', 'SchoolSubmissionHistory')
    print(f"☁️  Production - Using AWS DynamoDB")
    dynamodb = boto3.resource('dynamodb')

history_table = dynamodb.Table(HISTORY_TABLE_NAME)

# Cache for API keys (reduces Secrets Manager calls)
_api_keys_cache = None
_cache_timestamp = None
CACHE_TTL = 300  # 5 minutes

def get_api_keys():
    """
    Retrieve API keys from Secrets Manager with caching
    Returns: dict with 'enabled' (bool), 'keys' (list), and 'error' (str|None)

    SECURITY (FAIL-CLOSED): If the secret cannot be loaded for ANY reason
    (deleted, throttled, permissions issue, etc.), we do NOT disable auth.
    Instead we flag an 'error' so the handler can block requests with a
    503, rather than silently letting everyone in.
    """
    global _api_keys_cache, _cache_timestamp

    # Check cache
    current_time = datetime.datetime.now().timestamp()
    if _api_keys_cache and _cache_timestamp:
        if current_time - _cache_timestamp < CACHE_TTL:
            return _api_keys_cache

    secret_name = os.environ.get('SECRET_NAME', 'school-tracker/api-keys')

    try:
        response = secrets_client.get_secret_value(SecretId=secret_name)
        secret_data = json.loads(response['SecretString'])

        api_keys_config = {
            'enabled': secret_data.get('enabled', False),
            'keys': secret_data.get('api_keys', []),
            'error': None
        }

        # Update cache
        _api_keys_cache = api_keys_config
        _cache_timestamp = current_time

        print(f"✓ Loaded API key configuration from Secrets Manager ")
        return api_keys_config

    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_msg = str(e)

        if error_code == 'ResourceNotFoundException':
            print(f"🚨 CRITICAL: Secret '{secret_name}' not found in Secrets Manager")
            error_msg = f"Secret '{secret_name}' not found"
        elif error_code == 'InvalidRequestException':
            print(f"🚨 CRITICAL: Secret '{secret_name}' is marked for deletion / invalid state: {e}")
            error_msg = f"Secret '{secret_name}' is in an invalid state (possibly marked for deletion)"
        else:
            print(f"🚨 CRITICAL: Error retrieving secret: {e}")

        return {
            'enabled': True,
            'keys': [],
            'error': error_msg
        }

    except Exception as e:
        print(f"🚨 CRITICAL: Unexpected error getting API keys: {e}")
        return {
            'enabled': True,
            'keys': [],
            'error': str(e)
        }

def save_to_history(check_data):
    """
    Save submission check to DynamoDB with 30-day TTL
    """
    try:
        # Calculate TTL (30 days from now)
        ttl_timestamp = int((datetime.datetime.now() + datetime.timedelta(days=30)).timestamp())

        # Convert floats to Decimal for DynamoDB
        item = {
            'check_id': check_data['check_id'],
            'timestamp': int(datetime.datetime.now().timestamp()),
            'collection_date': check_data['collection_date'],
            'ttl': ttl_timestamp,
            'summary': {
                'total_schools': check_data['summary']['total_schools'],
                'unique_schools_submitted': check_data['summary']['unique_schools_submitted'],
                'missing_schools': check_data['summary']['missing_schools'],
                'completion_rate': check_data['summary']['completion_rate'],
                'status': check_data['summary']['status']
            },
            'missing_schools': check_data['missing_schools'],
            'source': check_data.get('source', 'unknown')
            
        }

        # Add duplicate info if exists
        if 'warnings' in check_data:
            item['warnings'] = check_data['warnings']

        history_table.put_item(Item=item)
        print(f"✓ Saved check {check_data['check_id']} to history")
        return True

    except Exception as e:
        print(f"⚠️  Error saving to history: {e}")
        return False

def get_history(limit=10):
    """
    Retrieve recent submission checks from DynamoDB
    """
    try:
        # Scan table and sort by timestamp (newest first)
        response = history_table.scan(
            Limit=limit
        )

        items = response.get('Items', [])

        # Sort by timestamp descending
        items.sort(key=lambda x: x.get('timestamp', 0), reverse=True)

        return items[:limit]

    except Exception as e:
        print(f"⚠️  Error retrieving history: {e}")
        return []

def parse_multipart_form_data(event):
    """
    Parse multipart/form-data from API Gateway
    Returns: dict with file content and other form fields
    """
    try:
        content_type = event.get('headers', {}).get('content-type', '') or event.get('headers', {}).get('Content-Type', '')

        if 'multipart/form-data' not in content_type:
            return None

        # Get boundary from content-type header
        boundary = content_type.split('boundary=')[-1]

        # Decode body (it's base64 encoded by API Gateway)
        if event.get('isBase64Encoded', False):
            body = base64.b64decode(event['body'])
        else:
            body = event['body'].encode('utf-8')

        # Parse multipart data
        parts = body.split(f'--{boundary}'.encode())

        files = {}
        fields = {}

        for part in parts:
            if b'Content-Disposition' in part:
                # Extract field name
                if b'name="' in part:
                    name_start = part.index(b'name="') + 6
                    name_end = part.index(b'"', name_start)
                    field_name = part[name_start:name_end].decode('utf-8')

                    # Extract content
                    content_start = part.index(b'\r\n\r\n') + 4
                    content_end = part.rfind(b'\r\n')
                    content = part[content_start:content_end]

                    # Check if it's a file
                    if b'filename="' in part:
                        files[field_name] = content.decode('utf-8')
                    else:
                        fields[field_name] = content.decode('utf-8')

        return {'files': files, 'fields': fields}

    except Exception as e:
        print(f"⚠️  Error parsing multipart data: {e}")
        return None

def lambda_handler(event, context):
    """
    School Submission Tracker API - v2 (Secrets Manager + DynamoDB) - Secure Fail-Closed
    Supports CSV file uploads and stores 30-day history in DynamoDB

    SECURITY: If Secrets Manager is unavailable (deleted, throttled, permission
    issue, etc.), the API fails CLOSED - it blocks authenticated endpoints with
    503 Service Unavailable instead of silently disabling authentication.
    """

    http_method = event.get('httpMethod', '')
    path = event.get('path', '')

    print(f"📨 Request: {http_method} {path}")

    disable_auth = os.environ.get('DISABLE_AUTH', 'false').lower() == 'true'

    # Home page never requires auth, so skip the Secrets Manager call entirely
    if path == '/':
        pass
    elif disable_auth:
        print("✓ Authentication disabled for local testing")
    else:
        # Get API key configuration from Secrets Manager
        api_config = get_api_keys()

        if api_config.get('error'):
            print(f"🚨 BLOCKING REQUEST: Cannot load API key configuration ({api_config['error']})")
            return {
                'statusCode': 503,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Service Unavailable',
                    'message': 'API authentication service is temporarily unavailable. Please try again later.',
                    'details': 'Unable to load authentication configuration'
                })
            }

        # API Key validation (if enabled in Secrets Manager)
        if api_config['enabled']:
            api_key = event.get('headers', {}).get('x-api-key', '') or event.get('headers', {}).get('X-Api-Key', '')

            if not api_key:
                print("🚨 BLOCKING REQUEST: Missing API key")
                return error_response(401, 'Missing API key. Include x-api-key header.')

            if api_key not in api_config['keys']:
                print("🚨 BLOCKING REQUEST: Invalid API key attempt")
                return error_response(403, 'Invalid API key. Access denied.')

            print(f"✓ Authenticated request with API key")

    # Handle GET / (API info)
    if http_method == 'GET' and path == '/':
        return get_api_info()

    # Handle POST /check-submissions (JSON - backward compatible)
    elif http_method == 'POST' and path == '/check-submissions':
        return check_submissions(event)

    # Handle POST /upload-csv (NEW: CSV file upload)
    elif http_method == 'POST' and path == '/upload-csv':
        return handle_csv_upload(event)

    # Handle GET /history (NEW: View recent checks)
    elif http_method == 'GET' and path == '/history':
        return get_history_endpoint(event)

    # Unknown endpoint
    else:
        return error_response(404, 'Endpoint not found')

def handle_csv_upload(event):
    """
    Handle CSV file upload with master and submitted schools
    Expected CSV format:
    Master Schools,Submitted Schools
    SCHOOL A,SCHOOL A
    SCHOOL B,
    SCHOOL C,SCHOOL C
    """
    try:
        # Parse multipart form data
        form_data = parse_multipart_form_data(event)

        if not form_data or 'files' not in form_data:
            return error_response(400, 'No file uploaded. Send CSV as multipart/form-data with field name "file"')

        # Get CSV file content
        csv_content = form_data['files'].get('file', '')

        if not csv_content:
            return error_response(400, 'Empty CSV file')

        print(f"📄 Received CSV file ({len(csv_content)} bytes)")

        # Parse CSV
        csv_reader = csv.DictReader(io.StringIO(csv_content))

        master_schools = []
        submitted_schools = []

        for row in csv_reader:
            # Get master school (required)
            master_school = row.get('Master Schools', '').strip()
            if master_school:
                master_schools.append(master_school)

            # Get submitted school (optional)
            submitted_school = row.get('Submitted Schools', '').strip()
            if submitted_school:
                submitted_schools.append(submitted_school)

        print(f"✓ Parsed CSV: {len(master_schools)} master schools, {len(submitted_schools)} submissions")

        if not master_schools:
            return error_response(400, 'No schools found in "Master Schools" column')

        if not submitted_schools:
            return error_response(400, 'No schools found in "Submitted Schools" column')

        # Run comparison logic (reuse existing function)
        result = compare_schools(master_schools, submitted_schools)
        result['source'] = 'csv_upload'

        # Save to history
        save_to_history(result)

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(result, indent=2)
        }

    except Exception as e:
        print(f"❌ Error handling CSV upload: {e}")
        return error_response(500, f'Error processing CSV: {str(e)}')

def get_history_endpoint(event):
    """
    Return recent submission history
    """
    try:
        # Get limit from query parameters (default: 10)
        query_params = event.get('queryStringParameters') or {}
        limit = int(query_params.get('limit', 10))

        # Cap at 50 to prevent abuse
        limit = min(limit, 50)

        # Get history from DynamoDB
        history = get_history(limit)

        # Convert Decimal to float for JSON serialization
        history_json = json.loads(json.dumps(history, default=str))

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'total_records': len(history),
                'retention_days': 30,
                'history': history_json
            }, indent=2)
        }

    except Exception as e:
        print(f"❌ Error retrieving history: {e}")
        return error_response(500, f'Error retrieving history: {str(e)}')

def get_api_info():
    """Return HTML documentation"""

    html_content = """
    <!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>School Submission Tracker API v2.0</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #FFFFFF;
            background: #1F3250;
            min-height: 100vh;
            padding: 20px;
        }

        .container {
            max-width: 1000px;
            margin: 0 auto;
            background: #1F3250;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.5);
            overflow: hidden;
            border: 1px solid #2C3E50;
        }

        .header {
            background: #2C3E50;
            color: #FFFFFF;
            padding: 60px 40px;
            text-align: center;
            border-bottom: 2px solid #3498DB;
        }

        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
            font-weight: 700;
        }

        .header .subtitle {
            font-size: 1.2em;
            opacity: 0.95;
            font-weight: 300;
            color: #95A5A6;
        }

        .status {
            display: inline-block;
            background: #DCFCE7;
            color: #15803D;
            padding: 8px 20px;
            border-radius: 20px;
            font-size: 0.9em;
            margin-top: 20px;
            font-weight: 500;
        }

        .security {
            display: inline-block;
            background: #FEE2E2;
            color: #991B1B;
            padding: 6px 16px;
            border-radius: 12px;
            font-size: 0.85em;
            margin: 5px;
            font-weight: 500;
        }

        .dynamo {
            display: inline-block;
            background: #E0F2FE;
            color: #0369A1;
            padding: 6px 16px;
            border-radius: 12px;
            font-size: 0.85em;
            margin: 5px;
            font-weight: 500;
        }

        .content {
            padding: 40px;
        }

        .section {
            margin-bottom: 40px;
        }

        .section h2 {
            color: #3498DB;
            font-size: 1.8em;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #2C3E50;
        }

        .new-badge {
            background: #F3E8FF;
            color: #6B21A8;
            padding: 4px 10px;
            border-radius: 8px;
            font-size: 0.7em;
            margin-left: 10px;
            font-weight: 600;
        }

        .endpoint {
            background: #2C3E50;
            padding: 25px;
            border-radius: 12px;
            margin-bottom: 20px;
            border: 2px solid #1F3250;
        }

        .method {
            display: inline-block;
            padding: 6px 16px;
            border-radius: 6px;
            font-weight: 600;
            font-size: 0.85em;
            letter-spacing: 0.5px;
        }

        .method.get {
            background: #1C8B41;
            color: #FFFFFF;
        }

        .method.post {
            background: #1070B2;
            color: #FFFFFF;
        }

        .code-block {
            background: #1F3250;
            color: #FFFFFF;
            padding: 20px;
            border-radius: 8px;
            overflow-x: auto;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
            line-height: 1.5;
            margin: 15px 0;
            border: 1px solid #2C3E50;
        }

        .response-label {
            color: #95A5A6;
            font-size: 0.85em;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-top: 15px;
            margin-bottom: 4px;
            font-weight: 600;
        }

        .tip {
            background: rgba(28, 139, 65, 0.12);
            border-left: 3px solid #1C8B41;
            padding: 12px 16px;
            border-radius: 6px;
            margin: 15px 0;
            color: #FFFFFF;
            font-size: 0.9em;
        }

        .info-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
            margin: 20px 0;
        }
        @media (max-width: 600px) {
            .info-grid {
            grid-template-columns: 1fr;
            }
        }

        .info-item {
            background: #2C3E50;
            padding: 15px;
            border-radius: 8px;
        }

        .info-label {
            font-weight: 600;
            color: #95A5A6;
            font-size: 0.85em;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 5px;
        }

        .info-value {
            color: #5EEAD4;
            font-size: 1.1em;
            font-weight: 500;
        }
    </style>
</head>

<body>
    <div class="container">
        <div class="header">
            <h1>🎓 School Submission Tracker API v2.0</h1>
            <p class="subtitle">Automated school data collection tracking for EMIS officers</p>
            <div class="status">🟢 API Online</div>
        </div>

        <div class="content">
            <div class="section">
                <h2>Overview</h2>
                <p>A serverless AWS REST API that helps Education Management Information System (EMIS) officers track school data submissions efficiently.
                The API is currently online, secured with AWS Secrets Manager authentication, and 30-day history tracking using DynamoDB.
                </p>
            </div>
 
            <div class="section">
                <h2>Features</h2>
                <div class="info-grid">            
                    <div class="info-item">
                        <div class="info-label" style="color: #3498DB;">Instant Comparison</div>
                        <div class="info-value"> Compare submitted schools list against master school list in seconds!</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label" style="color: #3498DB;">Duplicate Detection</div>
                        <div class="info-value">Automatically detects schools that submitted multiple times</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label" style="color: #3498DB;">Completion Rates</div>
                        <div class="info-value">Calculate submission progress and completion percentages</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label" style="color: #3498DB;">CSV Upload <span class="new-badge">NEW</span></div>
                        <div class="info-value">Eliminate JSON fromatting. Upload files directly!</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label" style="color: #3498DB;">30-Day History Tracking <span class="new-badge">NEW</span></div>
                        <div class="info-value">Track submission progress over time</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label" style="color: #3498DB;">Auto-Cleanup <span class="new-badge">NEW</span></div>
                        <div class="info-value">DynamoDB TTL removes old data automatically</div>
                    </div>
                </div>
            </div>

            <div class="section">
                <h2>Security Note</h2>
                <p><strong>Fail-Closed Authentication:</strong> If the API key configuration cannot be loaded from Secrets Manager for any reason, all authenticated endpoints return <code>503 Service Unavailable.</code></p>
            </div>

            <div class="section">
                <h2>🔗 Endpoints</h2>

                <!-- POST /upload-csv -->
                <div class="endpoint">
                    <div>
                        <span class="method post">POST</span>
                        <span style="font-family: monospace; font-weight: 600; color: #FFFFFF;">/upload-csv</span>
                        <span class="new-badge">NEW</span>
                    </div>
                    <p style="margin-top: 15px; color: #FFFFFF;"><strong style="color: #95A5A6;">Description:</strong> Upload CSV with master and submitted schools</p>
                    <p style="color: #FFFFFF;"><strong style="color: #95A5A6;">Content-Type:</strong> multipart/form-data</p>
                    <p style="color: #FFFFFF;"><strong style="color: #95A5A6;">Authentication:</strong> API key required (disabled in local testing mode)</p>
                    <p style="margin-top: 15px; color: #95A5A6;"><strong>CSV File Format (test-data.csv):</strong></p>
                    <div class="code-block">
<pre style="color: #E67E22;"><span style="color: #7F8C8D;">Master Schools,Submitted Schools</span>
SCHOOL A,SCHOOL A
SCHOOL B,
SCHOOL C,SCHOOL C</pre>
                    </div>

                    <div class="tip">
                        💡 <strong>Tip:</strong> Save your school lists to an actual file (e.g. <code>test-data.csv</code>)
                        and reference it with <code>-F "file=@test-data.csv"</code> — easier to reuse and re-run than
                        retyping data inline.
                    </div>

                    <p style="color: #95A5A6;"><strong>Example:</strong></p>
                    <div class="code-block">
<pre style="color: #FFFFFF;"><span style="color: #F39C12;">curl</span> -X POST http://localhost:3000/upload-csv \
  -H <span style="color: #E67E22;">"x-api-key: YOUR-API-KEY"</span> \
  -F <span style="color: #E67E22;">"file=@test-data.csv"</span></pre>
                    </div>

                    <p class="response-label"><strong>Expected Response:</strong></p>
                    <div class="code-block">
<pre style="color: #FFFFFF;">{
  <span style="color: #3498DB;">"check_id"</span>: <span style="color: #E67E22;">"a1b2c3d4-..."</span>,
  <span style="color: #3498DB;">"collection_date"</span>: <span style="color: #E67E22;">"2026-07-21"</span>,
  <span style="color: #3498DB;">"summary"</span>: {
    <span style="color: #3498DB;">"total_schools"</span>: <span style="color: #F39C12;">18</span>,
    <span style="color: #3498DB;">"unique_schools_submitted"</span>: <span style="color: #F39C12;">9</span>,
    <span style="color: #3498DB;">"missing_schools"</span>: <span style="color: #F39C12;">9</span>,
    <span style="color: #3498DB;">"completion_rate"</span>: <span style="color: #E67E22;">"50.0%"</span>,
    <span style="color: #3498DB;">"status"</span>: <span style="color: #E67E22;">"In progress - Keep sending reminders"</span>
  },
  <span style="color: #3498DB;">"missing_schools"</span>: [<span style="color: #E67E22;">"SCHOOL J"</span>, <span style="color: #E67E22;">"SCHOOL K"</span>, ...],
  <span style="color: #3498DB;">"submitted_schools"</span>: [<span style="color: #E67E22;">"SCHOOL A"</span>, <span style="color: #E67E22;">"SCHOOL B"</span>, ...],
  <span style="color: #3498DB;">"warnings"</span>: {
    <span style="color: #3498DB;">"duplicates_found"</span>: <span style="color: #F39C12;">1</span>,
    <span style="color: #3498DB;">"message"</span>: <span style="color: #E67E22;">"1 school(s) submitted multiple times."</span>
  }
}</pre>
                    </div>
                </div>

                <!-- GET /history -->
                <div class="endpoint">
                    <div>
                        <span class="method get">GET</span>
                        <span style="font-family: monospace; font-weight: 600; color: #FFFFFF;">/history?limit=10</span>
                        <span class="new-badge">NEW</span>
                    </div>
                    <p style="margin-top: 15px; color: #FFFFFF;"><strong style="color: #95A5A6;">Description:</strong> View recent submission checks (last 30 days)</p>
                    <p style="color: #FFFFFF;"><strong style="color: #95A5A6;">Authentication:</strong> API key required (disabled in local mode)</p>
                    <p style="color: #FFFFFF;"><strong style="color: #95A5A6;">Query Parameters:</strong> limit (default: 10, max: 50)</p>

                    <p style="margin-top: 15px; color: #95A5A6;"><strong>Example:</strong></p>
                    <div class="code-block">
<pre style="color: #FFFFFF;"><span style="color: #F39C12;">curl</span> -X GET <span style="color: #E67E22;">"http://localhost:3000/history?limit=5"</span> \
  -H <span style="color: #E67E22;">"x-api-key: YOUR-API-KEY"</span></pre>
                    </div>

                    <p class="response-label"><strong>Expected Response:</strong></p>
                    <div class="code-block">
<pre style="color: #FFFFFF;">{
  <span style="color: #3498DB;">"total_records"</span>: <span style="color: #F39C12;">1</span>,
  <span style="color: #3498DB;">"retention_days"</span>: <span style="color: #F39C12;">30</span>,
  <span style="color: #3498DB;">"history"</span>: [
    {
      <span style="color: #3498DB;">"check_id"</span>: <span style="color: #E67E22;">"a1b2c3d4-..."</span>,
      <span style="color: #3498DB;">"collection_date"</span>: <span style="color: #E67E22;">"2026-07-21"</span>,
      <span style="color: #3498DB;">"summary"</span>: {
        <span style="color: #3498DB;">"total_schools"</span>: <span style="color: #F39C12;">18</span>,
        <span style="color: #3498DB;">"completion_rate"</span>: <span style="color: #E67E22;">"50.0%"</span>,
        <span style="color: #3498DB;">"status"</span>: <span style="color: #E67E22;">"In progress - Keep sending reminders"</span>
      }
    }
  ]
}</pre>
                    </div>
                </div>

                <!-- POST /check-submissions -->
                <div class="endpoint">
                    <div>
                        <span class="method post">POST</span>
                        <span style="font-family: monospace; font-weight: 600; color: #FFFFFF;">/check-submissions</span>
                    </div>
                    <p style="margin-top: 15px; color: #FFFFFF;"><strong style="color: #95A5A6;">Description:</strong> JSON endpoint (backward compatible)</p>
                    <p style="color: #FFFFFF;"><strong style="color: #95A5A6;">Content-Type:</strong> application/json</p>
                    <p style="color: #FFFFFF;"><strong style="color: #95A5A6;">Authentication:</strong> API key required (disabled in local mode)</p>
                    <p style="color: #E67E22;"><strong style="color: #95A5A6;">Note:</strong> Use /upload-csv for easier workflow!</p>
                    <p style="margin-top: 15px; color: #95A5A6;"><strong>JSON File Format (test-data.json):</strong></p>
                    <div class="code-block">
<pre style="color: #FFFFFF;">{
<span style="color: #3498DB;">"master_schools"</span>: [<span style="color: #E67E22;">"SCHOOL A"</span>, <span style="color: #E67E22;">"SCHOOL B"</span>, <span style="color: #E67E22;">"SCHOOL C"</span>],
<span style="color: #3498DB;">"submitted_schools"</span>: [<span style="color: #E67E22;">"SCHOOL A"</span>, <span style="color: #E67E22;">"SCHOOL C"</span>]
}</pre>
                    </div>

                    <div class="tip">
                        💡 <strong>Tip:</strong> Save your school lists to an actual file (e.g. <code>test-data.json</code>)
                        and reference it with <code>-d "@test-data.json"</code> instead of typing JSON inline.
                    </div>

                    <p style="margin-top: 15px; color: #95A5A6;"><strong>Example:</strong></p>
                    <div class="code-block">
<pre style="color: #FFFFFF;"><span style="color: #F39C12;">curl</span> -X POST https://YOUR-API-URL/check-submissions \
  -H <span style="color: #E67E22;">"Content-Type: application/json"</span> \
  -H <span style="color: #E67E22;">"x-api-key: YOUR-API-KEY"</span> \
  -d <span style="color: #E67E22;">"@test-data.json"</span></pre>
                    </div>

                    <p class="response-label"><strong>Expected Response:</strong></p>
                    <div class="code-block">
<pre style="color: #FFFFFF;">{
  <span style="color: #3498DB;">"check_id"</span>: <span style="color: #E67E22;">"a1b2c3d4-..."</span>,
  <span style="color: #3498DB;">"summary"</span>: {
    <span style="color: #3498DB;">"total_schools"</span>: <span style="color: #F39C12;">3</span>,
    <span style="color: #3498DB;">"unique_schools_submitted"</span>: <span style="color: #F39C12;">2</span>,
    <span style="color: #3498DB;">"missing_schools"</span>: <span style="color: #F39C12;">1</span>,
    <span style="color: #3498DB;">"completion_rate"</span>: <span style="color: #E67E22;">"66.7%"</span>,
    <span style="color: #3498DB;">"status"</span>: <span style="color: #E67E22;">"In progress - Keep sending reminders"</span>
  },
  <span style="color: #3498DB;">"missing_schools"</span>: [<span style="color: #E67E22;">"SCHOOL B"</span>],
  <span style="color: #3498DB;">"submitted_schools"</span>: [<span style="color: #E67E22;">"SCHOOL A"</span>, <span style="color: #E67E22;">"SCHOOL C"</span>]
}</pre>
                    </div>
                </div>
            </div>

            <div class="section">
                <h2>⚙️ Quick Start</h2>
                <ol style="line-height: 2.5; padding-left: 20px; color: #FFFFFF;">
                    <li>Export Google Forms responses to CSV</li>
                    <li>Format CSV with two columns: <span style="color: #E67E22;">"Master Schools"</span> and <span style="color: #E67E22;">"Submitted Schools"</span></li>
                    <li>Upload CSV to <span style="color: #3498DB;">/upload-csv</span> endpoint</li>
                    <li>Get instant report + auto-saved to history</li>
                    <li>View past checks at <span style="color: #3498DB;">/history</span> endpoint</li>
                </ol>
            </div>
        </div>

        <div style="background: #2C3E50; padding: 30px 40px; text-align: center; border-top: 1px solid #1F3250;">
            <p style="color: #95A5A6;"> © 2026, Gloria Boakye - EMIS OFFICER, GES | AWS Community Builder (Serverless)</p>
        </div>
    </div>
</body>
</html>
    """
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'text/html',
            'Access-Control-Allow-Origin': '*'
        },
        'body': html_content
    }

def error_response(status_code, error_message):
    """Standard error response format"""
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps({'error': error_message})
    }

def normalize_school_name(name):
    """
    Normalize school names for reliable comparison
    """
    if not name:
        return ""

    name = str(name).strip()
    name = ' '.join(name.split())
    name = name.upper()

    return name

def parse_school_list(school_input):
    """
    Parse school list from various formats
    """
    if not school_input:
        return []

    schools = []

    if isinstance(school_input, list):
        for item in school_input:
            item = str(item).strip()
            if item and item.upper() != 'SCHOOL NAME':
                schools.append(item)
        if schools:
            return schools

    school_string = str(school_input)

    try:
        csv_reader = csv.reader(io.StringIO(school_string))
        for row in csv_reader:
            for cell in row:
                cell = cell.strip()
                if cell and cell.upper() != 'SCHOOL NAME':
                    schools.append(cell)
        if schools:
            return schools
    except:
        pass

    lines = school_string.split('\n')
    for line in lines:
        line = line.strip()
        if line and line.upper() != 'SCHOOL NAME':
            schools.append(line)

    return schools

def compare_schools(master_schools, submitted_schools):
    """
    Core comparison logic - extracted for reuse
    Returns standardized result dict
    """
    # Create normalized master list
    normalized_master = {normalize_school_name(s): s for s in master_schools}

    # Detect duplicates
    submission_counts = Counter([normalize_school_name(s) for s in submitted_schools])

    duplicates = []
    for normalized_name, count in submission_counts.items():
        if count > 1 and normalized_name in normalized_master:
            duplicates.append({
                'school': normalized_master[normalized_name],
                'submission_count': count,
                'note': f'Submitted {count} times (using most recent submission)'
            })

    # Get unique submitted schools
    submitted_normalized = set()
    submitted_schools_list = []

    for submitted in submitted_schools:
        normalized = normalize_school_name(submitted)
        if normalized in normalized_master:
            submitted_normalized.add(normalized)
            if normalized_master[normalized] not in submitted_schools_list:
                submitted_schools_list.append(normalized_master[normalized])

    # Calculate missing schools
    missing_schools = [
        s for s in master_schools
        if normalize_school_name(s) not in submitted_normalized
    ]

    # Statistics
    total_schools = len(master_schools)
    total_raw_submissions = len(submitted_schools)
    submitted_count = len(submitted_schools_list)
    missing_count = len(missing_schools)
    completion_rate = (submitted_count / total_schools * 100) if total_schools > 0 else 0
    duplicate_count = total_raw_submissions - submitted_count

    # Status
    if missing_count == 0:
        status = 'Complete - All schools submitted!'
    elif completion_rate >= 90:
        status = 'Almost complete - 90%+ submission rate'
    elif completion_rate >= 75:
        status = 'On track - 75%+ submission rate'
    else:
        status = 'In progress - Keep sending reminders'

    # Build result
    result = {
        'check_id': str(uuid.uuid4()),
        'timestamp': datetime.datetime.now().isoformat(),
        'collection_date': datetime.datetime.now().strftime('%Y-%m-%d'),
        'summary': {
            'total_schools': total_schools,
            'unique_schools_submitted': submitted_count,
            'total_raw_submissions': total_raw_submissions,
            'duplicate_submissions': duplicate_count,
            'missing_schools': missing_count,
            'completion_rate': f'{completion_rate:.1f}%',
            'status': status
        },
        'missing_schools': sorted(missing_schools),
        'submitted_schools': sorted(submitted_schools_list)
    }

    # Add duplicate info
    if duplicates:
        result['duplicate_submissions_details'] = sorted(duplicates, key=lambda x: x['submission_count'], reverse=True)
        result['warnings'] = {
            'duplicates_found': len(duplicates),
            'total_duplicate_submissions': duplicate_count,
            'message': f'{len(duplicates)} school(s) submitted multiple times.',
            'note': 'Review duplicate_submissions_details'
        }

    # Add next steps
    if missing_count > 0:
        result['next_steps'] = {
            'action': 'Send reminders to missing schools',
            'schools_to_contact': sorted(missing_schools)[:20],
            'total_to_contact': missing_count,
            'showing': f'Showing first {min(20, missing_count)} of {missing_count}'
        }

    return result

def check_submissions(event):
    """JSON endpoint - backward compatible"""

    try:
        if event.get('body'):
            body = json.loads(event['body'])
        else:
            body = {}
    except json.JSONDecodeError:
        return error_response(400, 'Invalid JSON in request body')

    master_schools_input = body.get('master_schools', '')
    submitted_schools_input = body.get('submitted_schools', '')

    if not master_schools_input or not submitted_schools_input:
        return error_response(400, 'Missing required fields: master_schools, submitted_schools')

    master_schools = parse_school_list(master_schools_input)
    submitted_schools = parse_school_list(submitted_schools_input)

    if not master_schools:
        return error_response(400, 'No schools found in master list')
    if not submitted_schools:
        return error_response(400, 'No schools found in submitted list')

    # Run comparison
    result = compare_schools(master_schools, submitted_schools)
    result['source'] = 'json_api'

    # Save to history
    save_to_history(result)

    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps(result, indent=2)
    }