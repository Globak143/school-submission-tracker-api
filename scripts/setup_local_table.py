#!/usr/bin/env python3
"""
Setup DynamoDB table locally for testing
Run this after starting docker-compose
"""

import boto3
from botocore.exceptions import ClientError

# Connect to local DynamoDB
dynamodb = boto3.resource(
    'dynamodb',
    endpoint_url='http://localhost:8000',
    region_name='us-east-1',
    aws_access_key_id='local',
    aws_secret_access_key='local'
)

TABLE_NAME = 'SchoolSubmissionHistory'

def create_table():
    """Create the submission history table"""
    try:
        table = dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {
                    'AttributeName': 'check_id',
                    'KeyType': 'HASH'  # Partition key
                },
                {
                    'AttributeName': 'timestamp',
                    'KeyType': 'RANGE'  # Sort key
                }
            ],
            AttributeDefinitions=[
                {
                    'AttributeName': 'check_id',
                    'AttributeType': 'S'
                },
                {
                    'AttributeName': 'timestamp',
                    'AttributeType': 'N'
                }
            ],
            BillingMode='PAY_PER_REQUEST',  # On-demand pricing
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'TimestampIndex',
                    'KeySchema': [
                        {
                            'AttributeName': 'timestamp',
                            'KeyType': 'HASH'
                        }
                    ],
                    'Projection': {
                        'ProjectionType': 'ALL'
                    }
                }
            ]
        )
        
        print(f"Creating table '{TABLE_NAME}'...")
        table.wait_until_exists()
        print(f"Table '{TABLE_NAME}' created successfully!")
        print(f"View it at: http://localhost:8001")
        return True
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceInUseException':
            print(f"Table '{TABLE_NAME}' already exists")
            return True
        else:
            print(f"Error creating table: {e}")
            return False

def seed_test_data():
    """Add some test data for demonstration"""
    import datetime
    import uuid
    
    table = dynamodb.Table(TABLE_NAME)
    
    test_checks = [
        {
            'check_id': str(uuid.uuid4()),
            'timestamp': int(datetime.datetime.now().timestamp()),
            'collection_date': '2025-11-12',
            'summary': {
                'total_schools': 165,
                'unique_schools_submitted': 150,
                'missing_schools': 15,
                'completion_rate': '90.9%',
                'status': 'Almost complete - 90%+ submission rate'
            },
            'missing_schools': ['SCHOOL A', 'SCHOOL B', 'SCHOOL C'],
            'submitted_schools': ['SCHOOL D', 'SCHOOL E'],
            'ttl': int((datetime.datetime.now() + datetime.timedelta(days=30)).timestamp())
        }
    ]
    
    for check in test_checks:
        table.put_item(Item=check)
        print(f"Added test check: {check['check_id'][:8]}...")
    
    print(f"Seeded {len(test_checks)} test records")

def list_tables():
    """List all tables in local DynamoDB"""
    client = boto3.client(
        'dynamodb',
        endpoint_url='http://localhost:8000',
        region_name='us-east-1',
        aws_access_key_id='local',
        aws_secret_access_key='local'
    )
    
    response = client.list_tables()
    tables = response.get('TableNames', [])
    
    print(f"\nTables in local DynamoDB:")
    for table in tables:
        print(f"  - {table}")
    print()

if __name__ == '__main__':
    print("Setting up local DynamoDB for School Tracker...")
    print()
    
    # Create table
    success = create_table()
    
    if success:
        # Seed test data
        print()
        seed_test_data()
        
        # List all tables
        print()
        list_tables()
        
        print("Local DynamoDB setup complete!")
        print()
        print("Next steps:")
        print("  1. Start SAM Local: sam local start-api --docker-network school-tracker-network")
        print("  2. Test CSV upload: curl -X POST http://localhost:3000/upload-csv -F 'file=@test.csv' -H 'x-api-key: test'")
        print("  3. View history: curl http://localhost:3000/history?limit=10 -H 'x-api-key: test'")
    else:
        print("Setup failed. Make sure Docker Compose is running:")
        print("   docker-compose up -d")