# Snowflake Async SQL API Client

A Python library for asynchronous interaction with Snowflake using the SQL API and JWT authentication. This library provides a high-level interface for executing queries with support for long-running operations, result partitioning, and parameterized queries.

## Features

- **Asynchronous Operations**: Built with `aiohttp` for non-blocking database operations
- **JWT Authentication**: Secure authentication using RSA private keys
- **Long-Running Query Support**: Automatic polling for queries that exceed immediate execution time
- **Result Partitioning**: Automatic handling of large result sets split across multiple partitions
- **Parameterized Queries**: Support for bound parameters with automatic type conversion
- **Comprehensive Error Handling**: Detailed error reporting and timeout management
- **Snowflake Type Conversion**: Automatic conversion between Python and Snowflake data types

## Installation

```bash
pip install snowflake-sql-api-async
```

### Requirements

- Python 3.8+
- aiohttp
- PyJWT[crypto]
- snowflake-connector-python
- cryptography

## Quick Start

### Basic Connection

```python
import asyncio
from snowflake_sql_api_async import connect

async def main():
    # Connect using private key file
    conn = connect(
        account="your-account",
        user="your-username",
        private_key_path="/path/to/private_key.pem",
        private_key_passphrase="your-passphrase",
        warehouse="your-warehouse",
        database="your-database",
        schema="your-schema"
    )
    
    try:
        # Execute a simple query
        results = await conn.execute_query("SELECT CURRENT_TIMESTAMP()")
        print(results)
    finally:
        await conn.close()

asyncio.run(main())
```

### Using Private Key Bytes

```python
# Load private key from bytes
with open("/path/to/private_key.p8", "rb") as key_file:
    private_key_bytes = key_file.read()

conn = connect(
    account="your-account",
    user="your-username",
    private_key=private_key_bytes,
    private_key_passphrase="your-passphrase"
)
```

## Usage Examples

### Parameterized Queries

```python
# Simple parameters
results = await conn.execute_query(
    "SELECT * FROM users WHERE age > ? AND city = ?",
    params=[25, "New York"]
)

# Array parameters for IN clauses
results = await conn.execute_query(
    "SELECT * FROM products WHERE category IN (?)",
    params=[["electronics", "books", "clothing"]]
)

# Explicit type binding
results = await conn.execute_query(
    "SELECT * FROM orders WHERE order_date = ?",
    params=[("DATE", "2024-01-15")]
)
```

### Statement Parameters

```python
from snowflake_sql_api_async import StatementParams

# Configure query execution parameters
statement_params: StatementParams = {
    "warehouse": "LARGE_WH",
    "query_tag": "data-analysis",
    "use_cached_result": True,
    "rows_per_resultset": 10000
}

results = await conn.execute_query(
    "SELECT * FROM large_table",
    statement_params=statement_params
)
```

### Long-Running Queries

```python
# Execute a long-running query with custom timeout
results = await conn.execute_query(
    "SELECT COUNT(*) FROM very_large_table GROUP BY complex_column",
    timeout_seconds=1800,  # 30 minutes
    poll_interval=5        # Check status every 5 seconds
)
```

### Context Manager Pattern

```python
async def query_with_context():
    conn = connect(
        account="your-account",
        user="your-username",
        private_key_path="/path/to/key.pem"
    )
    
    try:
        results = await conn.execute_query("SELECT 1 as test")
        return results
    finally:
        await conn.close()
```

## Authentication Setup

### Generating RSA Key Pair

```bash
# Generate private key
openssl genrsa -out snowflake_private_key.pem 2048

# Generate public key
openssl rsa -in snowflake_private_key.pem -pubout -out snowflake_public_key.pub

# Convert to PKCS#8 format (optional)
openssl pkcs8 -topk8 -inform PEM -outform PEM -nocrypt \
    -in snowflake_private_key.pem -out snowflake_private_key.p8
```

### Configure Snowflake User

```sql
-- Set the public key for your user
ALTER USER your_username SET RSA_PUBLIC_KEY='MIIBIjANBgkqhkiG9w0B...';

-- Verify the key is set
DESC USER your_username;
```

## Connection Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `account` | str | Yes | Snowflake account identifier |
| `user` | str | Yes | Snowflake username |
| `private_key` | bytes | No* | Private key as bytes |
| `private_key_path` | str | No* | Path to private key file |
| `private_key_passphrase` | str | No | Passphrase for encrypted private key |
| `role` | str | No | Snowflake role to assume |
| `warehouse` | str | No | Default warehouse |
| `database` | str | No | Default database |
| `schema` | str | No | Default schema |

*Either `private_key` or `private_key_path` must be provided.

## Error Handling

```python
import asyncio
from aiohttp import ClientError

try:
    results = await conn.execute_query("INVALID SQL")
except RuntimeError as e:
    print(f"Query execution failed: {e}")
except asyncio.TimeoutError:
    print("Query timed out")
except ClientError as e:
    print(f"Network error: {e}")
```

## Best Practices

### Connection Management

- Always call `await conn.close()` when finished
- Use try/finally blocks or context managers
- Reuse connections for multiple queries when possible

### Query Optimization

- Use parameterized queries to prevent SQL injection
- Set appropriate timeouts for long-running operations
- Use `rows_per_resultset` to limit memory usage for large results
- Enable result caching with `use_cached_result` for repeated queries

### Security

- Store private keys securely and never commit them to version control
- Use environment variables or secure key management systems
- Rotate keys regularly
- Use specific roles with minimal required permissions

## Development

### Running Tests

```bash
# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov=snowflake_sql_api_async
```

### Code Formatting

```bash
# Format code
black .
isort .

# Type checking
mypy snowflake_sql_api_async/
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Changelog

### Version 0.0.1
- Initial release
- Async SQL API client with JWT authentication
- Support for parameterized queries and result partitioning
- Comprehensive error handling and timeout management

## Support

For issues and questions:
- Check the [GitHub Issues](https://github.com/username/snowflake-sql-api-async/issues)
- Review Snowflake's [SQL API documentation](https://docs.snowflake.com/en/developer-guide/sql-api/index.html)
- Consult the [Snowflake Python connector documentation](https://docs.snowflake.com/en/user-guide/python-connector.html)