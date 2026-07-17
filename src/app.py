import json
import csv
import io
import datetime
import os
import boto3
from botocore.exceptions import ClientError
from collections import Counter

# Initialize AWS clients
secrets_client = boto3.client('secretsmanager')

# Cache for API keys (reduces Secrets Manager calls)
_api_keys_cache = None
_cache_timestamp = None
CACHE_TTL = 300  # 5 minutes

def get_api_keys():
    """
    Retrieve API keys from Secrets Manager with caching
    Returns: dict with 'enabled' (bool), 'keys' (list), and 'error' (str|None)

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

        print(f"✓ Successfully loaded API keys from Secrets Manager (enabled: {api_keys_config['enabled']})")
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

def lambda_handler(event, context):
    """
    School Submission Tracker API - v1 (Secrets Manager) - Secure Fail-Closed Version
    Compares submitted schools against master list
    API Keys stored in AWS Secrets Manager

    """

    http_method = event.get('httpMethod', '')
    path = event.get('path', '')

    print(f"📨 Request: {http_method} {path}")

    # CHECK FOR LOCAL TESTING MODE FIRST 
    disable_auth = os.environ.get('DISABLE_AUTH', 'false').lower() == 'true'

    
    if path == '/':
        pass
    elif disable_auth:
        print("✓ Authentication disabled for local testing")
    else:
        # Get API key configuration from Secrets Manager
        api_config = get_api_keys()

        # SECURITY: If config failed to load, block all authenticated requests
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

            # Log successful authentication 
            print(f"✓ Authenticated request with API key")

    # Handle GET / (API info)
    if http_method == 'GET' and path == '/':
        return get_api_info()

    # Handle POST /check-submissions (main functionality)
    elif http_method == 'POST' and path == '/check-submissions':
        return check_submissions(event)

    # Unknown endpoint
    else:
        return error_response(404, 'Endpoint not found')

def get_api_info():
    """Return beautiful HTML documentation"""

    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>School Submission Tracker API</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                line-height: 1.6;
                color: #333;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                padding: 20px;
            }
            
            .container {
                max-width: 1000px;
                margin: 0 auto;
                background: white;
                border-radius: 20px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                overflow: hidden;
            }
            
            .header {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 60px 40px;
                text-align: center;
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
            }
            
            .status {
                display: inline-block;
                background: #10b981;
                color: white;
                padding: 8px 20px;
                border-radius: 20px;
                font-size: 0.9em;
                margin-top: 20px;
                font-weight: 500;
            }
            
            .content {
                padding: 40px;
            }
            
            .section {
                margin-bottom: 40px;
            }
            
            .section h2 {
                color: #667eea;
                font-size: 1.8em;
                margin-bottom: 20px;
                padding-bottom: 10px;
                border-bottom: 2px solid #f3f4f6;
            }
            
            .endpoint {
                background: #f9fafb;
                padding: 25px;
                border-radius: 12px;
                margin-bottom: 20px;
                border: 2px solid #e5e7eb;
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
                background: #10b981;
                color: white;
            }
            
            .method.post {
                background: #3b82f6;
                color: white;
            }
            
            .code-block {
                background: #1f2937;
                color: #e5e7eb;
                padding: 20px;
                border-radius: 8px;
                overflow-x: auto;
                font-family: 'Courier New', monospace;
                font-size: 0.9em;
                line-height: 1.5;
                margin: 15px 0;
            }
            
            .security-badge {
                display: inline-flex;
                align-items: center;
                background: #10b981;
                color: white;
                padding: 6px 12px;
                border-radius: 12px;
                font-size: 0.85em;
                margin-top: 10px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🏫 School Submission Tracker API</h1>
                <p class="subtitle">Automated school data collection tracking for EMIS officers</p>
                <div class="status">API Online</div>
                <div class="security-badge">🔒 Secured with AWS Secrets Manager</div>
            </div>
            
            <div class="content">
                <div class="section">
                    <h2>📊 Overview</h2>
                    <p>A serverless AWS API that helps Education Management Information System (EMIS) officers track school data submissions efficiently.</p>
                </div>

                <div class="section">
                    <h2>🔐 Security Note</h2>
                    <p><strong>Fail-Closed Authentication:</strong> If the API key configuration cannot be loaded from Secrets Manager for any reason, all authenticated endpoints return <code>503 Service Unavailable.</code></p>
                </div>
                
                <div class="section">
                    <h2>🔗 Endpoints</h2>
                    
                    <div class="endpoint">
                        <span class="method get">GET</span>
                        <span style="font-family: monospace; font-weight: 600;">/</span>
                        <p style="margin-top: 15px;"><strong>Description:</strong> Returns this API documentation page</p>
                        <p><strong>Authentication:</strong> None required</p>
                    </div>
                    
                    <div class="endpoint">
                        <span class="method post">POST</span>
                        <span style="font-family: monospace; font-weight: 600;">/check-submissions</span>
                        <p style="margin-top: 15px;"><strong>Description:</str> Check which schools have submitted their termly data and identify schools that have not(missing schools)</p>
                        <p><strong>Authentication:</strong> API key required (x-api-key header)</p>
                        <div class="code-block">
<pre>curl -X POST https://YOUR-API-URL/check-submissions \\
  -H "Content-Type: application/json" \\
  -H "x-api-key: YOUR-API-KEY" \\
  -d '{
    "master_schools": ["SCHOOL A", "SCHOOL B", "SCHOOL C"],
    "submitted_schools": ["SCHOOL A", "SCHOOL C"]
  }'</pre>
                        </div>
                    </div>
                </div>
            </div>
            
            <div style="background: #f9fafb; padding: 30px 40px; text-align: center; border-top: 1px solid #e5e7eb;">
                <p style="color: #6b7280;"> © 2025, Gloria Boakye - EMIS OFFICER, GES | AWS Community Builder (Serverless) </p>
                <p style="color: #9ca3af; font-size: 0.9em; margin-top: 5px;">AWS Lambda + API Gateway + Secrets Manager + SAM</p>
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

def check_submissions(event):
    """Main function to check school submissions"""
    
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
    
    normalized_master = {normalize_school_name(s): s for s in master_schools}
    submission_counts = Counter([normalize_school_name(s) for s in submitted_schools])
    
    duplicates = []
    for normalized_name, count in submission_counts.items():
        if count > 1 and normalized_name in normalized_master:
            duplicates.append({
                'school': normalized_master[normalized_name],
                'submission_count': count,
                'note': f'Submitted {count} times (using most recent submission)'
            })
    
    submitted_normalized = set()
    submitted_schools_list = []
    
    for submitted in submitted_schools:
        normalized = normalize_school_name(submitted)
        if normalized in normalized_master:
            submitted_normalized.add(normalized)
            if normalized_master[normalized] not in submitted_schools_list:
                submitted_schools_list.append(normalized_master[normalized])
    
    missing_schools = [
        s for s in master_schools 
        if normalize_school_name(s) not in submitted_normalized
    ]
    
    total_schools = len(master_schools)
    total_raw_submissions = len(submitted_schools)
    submitted_count = len(submitted_schools_list)
    missing_count = len(missing_schools)
    completion_rate = (submitted_count / total_schools * 100) if total_schools > 0 else 0
    duplicate_count = total_raw_submissions - submitted_count
    
    if missing_count == 0:
        status = 'Complete - All schools submitted!'
    elif completion_rate >= 90:
        status = 'Almost complete - 90%+ submission rate'
    elif completion_rate >= 75:
        status = 'On track - 75%+ submission rate'
    else:
        status = 'In progress - Keep sending reminders'
    
    response_data = {
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
    
    if duplicates:
        response_data['duplicate_submissions_details'] = sorted(duplicates, key=lambda x: x['submission_count'], reverse=True)
        response_data['warnings'] = {
            'duplicates_found': len(duplicates),
            'total_duplicate_submissions': duplicate_count,
            'message': f'{len(duplicates)} school(s) submitted multiple times. Using most recent submission for each.',
            'note': 'Review duplicate_submissions_details to see which schools submitted multiple times'
        }
    
    if missing_count > 0:
        response_data['next_steps'] = {
            'action': 'Send reminders to missing schools',
            'schools_to_contact': sorted(missing_schools)[:20],
            'total_to_contact': missing_count,
            'showing': f'Showing first {min(20, missing_count)} of {missing_count}'
        }
    
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps(response_data, indent=2)
    }