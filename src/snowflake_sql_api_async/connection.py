import aiohttp
import json
import asyncio
import jwt
from datetime import datetime, timedelta, timezone
from snowflake.connector.converter import SnowflakeConverter
from snowflake.connector.connection import TypeAndBinding
from cryptography.hazmat.backends import default_backend
import os
import time
from typing import (
    List,
    Dict,
    Any,
    Optional,
    Sequence,
    Text,
    cast,
    Union,
    Tuple,
    TypedDict,
)
import uuid
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
    load_der_private_key,
)
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
import base64
import hashlib
import logging
import sys

# Configure a logger for the JWTGenerator and the Connection class
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False


class StatementParams(TypedDict, total=False):
    """A dictionary of session parameters to set for a statement.
    All keys are optional unless otherwise noted.
    See: https://docs.snowflake.com/en/developer-guide/sql-api/reference.html#request-body

    Attributes:
        binary_output_format (str): Specifies format for VARCHAR values returned as
            output by BINARY-to-VARCHAR conversion functions. Example: 'HEX'.
        client_result_chunk_size (int): Specifies the maximum size of each set
            (or chunk) of query results to download (in MB). Example: 100.
        date_output_format (str): Specifies the display format for the DATE data type.
            Example: 'YYYY-MM-DD'.
        multi_statement_count (int): (Required for multi-statement requests) Specifies
            the number of SQL statements. 0 for variable count. Example: 2.
        query_tag (str): Query tag that you want to associate with the SQL statement.
            Example: 'tag-1234'.
        rows_per_resultset (int): Specifies the maximum number of rows returned in a
            result set, with 0 (default) meaning no maximum. Example: 200.
        time_output_format (str): Specifies the display format for the TIME data type.
            Example: 'HH24:MI:SS'.
        timestamp_ltz_output_format (str): Specifies the display format for the
            TIMESTAMP_LTZ data type. Example: 'YYYY-MM-DD HH24:MI:SS.FF3'.
        timestamp_ntz_output_format (str): Specifies the display format for the
            TIMESTAMP_NTZ data type. Example: 'YYYY-MM-DD HH24:MI:SS.FF3'.
        timestamp_output_format (str): Specifies the display format for the
            TIMESTAMP data type alias. Example: 'YYYY-MM-DD HH24:MI:SS.FF3 TZHTZM'.
        timestamp_tz_output_format (str): Specifies the display format for the
            TIMESTAMP_TZ data type. Example: 'YYYY-MM-DD HH24:MI:SS.FF3'.
        timezone (str): Time zone to use when executing the statement.
            Example: 'America/Los_Angeles'.
        use_cached_result (bool): Whether query results can be reused between
            successive invocations of the same query. Example: True.
    """

    binary_output_format: str
    client_result_chunk_size: int
    date_output_format: str
    multi_statement_count: int
    query_tag: str
    rows_per_resultset: int
    time_output_format: str
    timestamp_ltz_output_format: str
    timestamp_ntz_output_format: str
    timestamp_output_format: str
    timestamp_tz_output_format: str
    timezone: str
    use_cached_result: bool


class JWTGenerator(object):
    """
    Creates and signs a JWT.
    """

    LIFETIME = timedelta(minutes=59)
    RENEWAL_DELTA = timedelta(minutes=54)
    ALGORITHM = "RS256"

    def __init__(
            self,
            account: Text,
            user: Text,
            private_key: Optional[bytes] = None,
            private_key_file_path: Optional[Text] = None,
            private_key_passphrase: Optional[Text] = None,
            lifetime: timedelta = LIFETIME,
            renewal_delay: timedelta = RENEWAL_DELTA,
    ):
        if not (private_key_file_path or private_key) or (
                private_key_file_path and private_key
        ):
            raise ValueError(
                "Provide either 'private_key' or 'private_key_file_path', but not both."
            )

        logger.info(
            "Creating JWTGenerator for account '%s' and user '%s'", account, user
        )
        self.account = self._prepare_account_name_for_jwt(account)
        self.user = user.upper()
        self.qualified_username = f"{self.account}.{self.user}"
        self.lifetime = lifetime
        self.renewal_delay = renewal_delay
        self.renew_time = datetime.now(timezone.utc)
        self.token: Optional[Text] = None
        self.private_key: RSAPrivateKey

        try:
            if private_key:
                self.private_key = cast(
                    RSAPrivateKey,
                    load_der_private_key(
                        private_key,
                        password=private_key_passphrase.encode()
                        if private_key_passphrase
                        else None,
                        backend=default_backend(),
                    ),
                )
            elif private_key_file_path:
                with open(private_key_file_path, "rb") as pem_in:
                    pemlines = pem_in.read()
                self.private_key = cast(
                    RSAPrivateKey,
                    load_pem_private_key(
                        pemlines,
                        password=private_key_passphrase.encode()
                        if private_key_passphrase
                        else None,
                        backend=default_backend(),
                    ),
                )
        except Exception as e:
            raise ValueError(f"Failed to load private key: {e}") from e

    def _prepare_account_name_for_jwt(self, raw_account: Text) -> Text:
        """Prepare the account identifier for use in the JWT."""
        account = raw_account
        # Handle account identifiers for different cloud providers
        if ".global" not in account:
            # Legacy account locator format
            idx = account.find(".")
            if idx > 0:
                account = account[0:idx]
        else:
            # New account locator format (e.g., with region and cloud)
            idx = account.find("-")
            if idx > 0:
                account = account[0:idx]
        return account.upper()

    def get_token(self) -> Text:
        """Generates or returns a cached JWT."""
        now = datetime.now(timezone.utc)
        if self.token is None or self.renew_time <= now:
            logger.info("Generating a new JWT.")
            self.renew_time = now + self.renewal_delay
            public_key_fp = self._calculate_public_key_fingerprint(self.private_key)

            # Corrected payload structure
            payload = {
                "iss": f"{self.qualified_username}.{public_key_fp}",
                "sub": self.qualified_username,
                "iat": now,
                "exp": now + self.lifetime,
            }
            # The jwt library expects the payload's time values to be integers
            payload["iat"] = int(payload["iat"].timestamp())
            payload["exp"] = int(payload["exp"].timestamp())

            token = jwt.encode(
                payload, self.private_key, algorithm=JWTGenerator.ALGORITHM
            )
            self.token = token
        return self.token

    def _calculate_public_key_fingerprint(self, private_key: RSAPrivateKey) -> Text:
        """Calculates the SHA256 fingerprint of the public key."""
        public_key_raw = private_key.public_key().public_bytes(
            Encoding.DER, PublicFormat.SubjectPublicKeyInfo
        )
        sha256hash = hashlib.sha256()
        sha256hash.update(public_key_raw)
        public_key_fp = "SHA256:" + base64.b64encode(sha256hash.digest()).decode(
            "utf-8"
        )
        return public_key_fp


class Connection:
    """
    A Python client that uses the Snowflake SQL API for asynchronous query execution,
    now with full handling for long-running queries and partitioned results.
    """

    def __init__(
            self,
            account: str,
            user: str,
            private_key: Optional[bytes] = None,
            private_key_file_path: Optional[str] = None,
            private_key_passphrase: Optional[str] = None,
            role: Optional[str] = None,
            warehouse: Optional[str] = None,
            database: Optional[str] = None,
            schema: Optional[str] = None,
    ):
        """Initializes the Connection wrapper for the Snowflake SQL API."""
        self.account = account
        self.user = user
        self.role = role
        self.warehouse = warehouse
        self.database = database
        self.schema = schema
        self.base_url = (
            f"https://{self.account}.snowflakecomputing.com/api/v2/statements"
        )
        self._jwt_generator = JWTGenerator(
            account=self.account,
            user=self.user,
            private_key=private_key,
            private_key_file_path=private_key_file_path,
            private_key_passphrase=private_key_passphrase,
        )
        self._http_client: Optional[aiohttp.ClientSession] = None
        self._client_timeout = aiohttp.ClientTimeout(total=360.0)  # Increased timeout
        self.converter = SnowflakeConverter()
        logger.info("Snowflake connection (SQL API wrapper) initialized successfully.")

    def _generate_jwt_token(self) -> str:
        """Delegates JWT token generation."""
        return self._jwt_generator.get_token()

    async def _get_or_create_session(self) -> aiohttp.ClientSession:
        """Lazily creates the aiohttp.ClientSession if it doesn't exist."""
        if self._http_client is None or self._http_client.closed:
            self._http_client = aiohttp.ClientSession(timeout=self._client_timeout)
        return self._http_client

    async def _make_request(
            self,
            method: str,
            endpoint: str,
            json_data: Optional[Dict[str, Any]] = None,
            params: Optional[Dict[str, Any]] = None,
    ) -> aiohttp.ClientResponse:
        """
        Makes an async HTTP request and returns the full response object.
        Error handling is now based on the returned response object.
        """
        session = await self._get_or_create_session()
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self._generate_jwt_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Snowflake-Authorization-Token-Type": "KEYPAIR_JWT",
        }
        if self.role:
            headers["X-Snowflake-Role"] = self.role

        return await session.request(
            method, url, headers=headers, json=json_data, params=params
        )

    async def _process_and_fetch_partitions(
            self, final_response_json: Dict[str, Any], statement_handle: str
    ) -> List[Dict[str, Any]]:
        """
        Processes a final query response, fetches all partitions, and combines them.
        """
        all_results = []
        meta = final_response_json.get("resultSetMetaData", {})
        column_names = [col["name"] for col in meta.get("rowType", [])]

        initial_data = final_response_json.get("data", [])
        all_results.extend([dict(zip(column_names, row)) for row in initial_data])

        partitions = meta.get("partitionInfo")
        if partitions and len(partitions) > 1:
            logger.info(
                f"Result set is partitioned into {len(partitions)} chunks. Fetching all."
            )

            partition_tasks = [
                self._fetch_single_partition(statement_handle, i)
                for i in range(1, len(partitions))
            ]

            partition_results = await asyncio.gather(*partition_tasks)

            for partition_data in partition_results:
                all_results.extend([
                    dict(zip(column_names, row)) for row in partition_data
                ])

        return all_results

    async def _fetch_single_partition(
            self, statement_handle: str, partition_index: int
    ) -> List[List[Any]]:
        """Fetches and returns the data for a single result partition."""
        logger.debug(f"Fetching partition {partition_index}...")
        partition_response = await self._make_request(
            "GET", f"/{statement_handle}", params={"partition": partition_index}
        )
        async with partition_response:
            partition_response.raise_for_status()
            partition_json = await partition_response.json()
            return partition_json.get("data", [])

    async def execute_query(
            self,
            sql_text: str,
            params: Optional[Sequence[Any]] = None,
            statement_params: Optional[StatementParams] = None,
            timeout_seconds: int = 300,
            poll_interval: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        Executes a SQL query, handles the 202 polling fallback, and fetches all partitions.

        Args:
            sql_text: The SQL query to execute (using '?' for placeholders).
            params: An optional sequence of parameters to bind to the placeholders in the SQL.
            statement_params: An optional dictionary of session parameters to set for the statement.
            timeout_seconds: The total time to wait for the query to complete.

        Returns:
            A list of dictionaries, where each dictionary represents a row.
        """
        request_id = str(uuid.uuid4())
        statement_payload: dict[str, Any] = {
            "statement": sql_text,
            "timeout": timeout_seconds,
            "resultSetMetaData": {"format": "jsonv2"},
        }
        if self.warehouse:
            statement_payload["warehouse"] = self.warehouse
        if self.database:
            statement_payload["database"] = self.database
        if self.schema:
            statement_payload["schema"] = self.schema

        if params:
            statement_payload["bindings"] = self._process_params_qmarks(params)

        if statement_params:
            statement_payload["parameters"] = statement_params

        logger.info(f"Submitting query (Request ID: {request_id}): {sql_text[:100]}...")

        try:
            submit_response = await self._make_request(
                "POST",
                f"?async=true&requestId={request_id}",
                json_data=statement_payload,
            )

            final_response_json = None
            statement_handle = None

            async with submit_response:
                response_json = await submit_response.json()
                if submit_response.status >= 400:
                    raise RuntimeError(f"Error submitting query: {response_json}")

                statement_handle = response_json.get("statementHandle")
                if not statement_handle:
                    raise RuntimeError(
                        f"Failed to get statement handle: {response_json}"
                    )

                if submit_response.status == 202:
                    logger.info(
                        f"Query running (202 Accepted). Polling status for handle: {statement_handle}"
                    )
                    start_time = time.time()
                    while time.time() - start_time < timeout_seconds:
                        status_response = await self._make_request(
                            "GET", f"/{statement_handle}?requestId={request_id}"
                        )
                        async with status_response:
                            status_json = await status_response.json()
                            if status_response.status >= 400:
                                raise RuntimeError(
                                    f"Error polling status: {status_json}"
                                )

                            code = status_json.get("code")

                            if code == "090001":  # Query has completed successfully
                                logger.info("Polling successful. Query finished.")
                                final_response_json = status_json
                                break
                            elif code == "090004":  # Query is still running
                                logger.debug("Query still running. Waiting...")
                                await asyncio.sleep(poll_interval)
                            else:
                                message = status_json.get(
                                    "message",
                                    "An unknown error occurred during polling.",
                                )
                                raise RuntimeError(
                                    f"Query failed with code {code}: {message}"
                                )
                    if final_response_json is None:
                        # Attempt to cancel the query on timeout
                        await self._make_request("POST", f"/{statement_handle}/cancel")
                        raise asyncio.TimeoutError(
                            f"Query polling timed out after {timeout_seconds} seconds."
                        )

                elif submit_response.status == 200:
                    logger.info("Query completed immediately (200 OK).")
                    final_response_json = response_json

                else:
                    raise RuntimeError(
                        f"Unexpected status code {submit_response.status}: {await submit_response.text()}"
                    )

            if final_response_json:
                return await self._process_and_fetch_partitions(
                    final_response_json, statement_handle
                )
            else:
                raise RuntimeError("Failed to obtain a final query result.")

        except (
                aiohttp.ClientError,
                json.JSONDecodeError,
                RuntimeError,
                asyncio.TimeoutError,
        ) as e:
            logger.error(f"Error during query execution: {e}", exc_info=True)
            raise

    async def close(self):
        """Closes the underlying HTTP client."""
        if self._http_client and not self._http_client.closed:
            await self._http_client.close()
        logger.info("Snowflake SQL API client 'connection' has been closed.")

    def _get_snowflake_type_and_binding(
            self,
            v: Union[Tuple[str, Any], Any],
    ) -> TypeAndBinding:
        if isinstance(v, tuple):
            if len(v) != 2:
                raise ValueError(
                    f"Binding parameters must be a list where one element is a single value or a pair of Snowflake datatype and a value. Got tuple: {v}"
                )
            snowflake_type, val = v
        else:
            val = v
            snowflake_type = self.converter.snowflake_type(val)
            if snowflake_type is None:
                raise ValueError(
                    f"Python data type [{val.__class__.__name__.lower()}] cannot be automatically mapped to Snowflake data type. Specify the snowflake data type explicitly."
                )
        return TypeAndBinding(
            snowflake_type,
            self.converter.to_snowflake_bindings(snowflake_type, val),
        )

    def _process_params_qmarks(
            self,
            params: Optional[Sequence[Any]],
    ) -> Optional[Dict[str, Dict[str, Any]]]:
        """
        Modified from snowflake-connector-python to process 'qmark' style bindings.
        """
        if not params:
            return None
        processed_params: Dict[str, Dict[str, Any]] = {}

        for idx, v in enumerate(params):
            if isinstance(v, list):
                # This block handles binding a list to an IN clause, for example
                all_param_data = list(map(self._get_snowflake_type_and_binding, v))

                # Use the type of the first element for the array, assuming homogeneity
                first_type = "TEXT"  # Default
                if all_param_data:
                    first_type = all_param_data[0].type

                processed_params[str(idx + 1)] = {
                    "type": f"{first_type}_ARRAY",  # Snowflake API expects type name with _ARRAY suffix
                    "value": [param_data.binding for param_data in all_param_data],
                }
            else:
                snowflake_type, snowflake_binding = (
                    self._get_snowflake_type_and_binding(v)
                )
                processed_params[str(idx + 1)] = {
                    "type": snowflake_type,
                    "value": snowflake_binding,
                }
        if logger.getEffectiveLevel() <= logging.DEBUG:
            for k, v_dict in processed_params.items():
                logger.debug("idx: %s, type: %s", k, v_dict.get("type"))
        return processed_params


def connect(
        account: str,
        user: str,
        private_key: Optional[bytes] = None,
        private_key_path: Optional[str] = None,
        private_key_passphrase: Optional[str] = None,
        role: Optional[str] = None,
        warehouse: Optional[str] = None,
        database: Optional[str] = None,
        schema: Optional[str] = None,
        **kwargs: Any,
) -> Connection:
    """Establishes a logical 'connection' by initializing the SQL API client."""
    if private_key_path and not os.path.exists(private_key_path):
        raise FileNotFoundError(f"Private key file not found at: {private_key_path}")

    return Connection(
        account=account,
        user=user,
        private_key=private_key,
        private_key_file_path=private_key_path,
        private_key_passphrase=private_key_passphrase,
        role=role,
        warehouse=warehouse,
        database=database,
        schema=schema,
    )
