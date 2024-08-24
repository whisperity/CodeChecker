// -------------------------------------------------------------------------
//  Part of the CodeChecker project, under the Apache License v2.0 with
//  LLVM Exceptions. See LICENSE for license information.
//  SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// -------------------------------------------------------------------------

/**
 * Helper enum for expressing a three-way boolean in a filter.
 */
enum Ternary {
  BOTH = 0, // Indicates a query where both set and unset booleans are matched.
  OFF  = 1, // Indicates a query where the filter matches an UNSET boolean.
  ON   = 2, // Indicates a query where the filter matches a SET boolean.
}

enum ErrorCode {
  // Any other sort of error encountered during RPC execution.
  GENERAL  = 2,

  // Executing the request triggered a database-level fault, constraint violation.
  DATABASE = 0,

  // The request is malformed or an internal I/O operation failed.
  IOERROR  = 1,

  // Authentication denied. We do not allow access to the service.
  AUTH_DENIED = 3,

  // User does not have the necessary rights to perform an action.
  UNAUTHORIZED = 4,

  // The client attempted to query an API version that is not supported by the
  // server.
  API_MISMATCH = 5,

  // REMOVED IN API v6.59 (CodeChecker v6.25.0)!
  // Previously sent by report_server.thrif/codeCheckerDBAccess::massStoreRun()
  // when the client uploaded a source file which contained errors, such as
  // review status source-code-comment errors.
  /* SOURCE_FILE = 6, */ // Never reuse the value of the enum constant!

  // REMOVED IN API v6.59 (CodeChecker v6.25.0)!
  // Previously sent by report_server.thrif/codeCheckerDBAccess::massStoreRun()
  // when the client uploaded a report with annotations that had invalid types.
  /* REPORT_FORMAT = 7, */ // Never reuse the value of the enum constant!
}

exception RequestFailed {
  1: ErrorCode    errorCode,
  2: string       message,
  3: list<string> extraInfo
}

/**
 * The following permission scopes exist.
 *
 * SYSTEM: These permissions are global to the running CodeChecker server.
 *   In this case, the 'extraParams' field is empty.
 *
 * PRODUCT: These permissions are configured per-product.
 *   The extra data field looks like the following object:
 *     { i64 productID }
 */
enum Permission {
  SUPERUSER       = 1,         // scope: SYSTEM
  PERMISSION_VIEW = 2,         // scope: SYSTEM

  PRODUCT_ADMIN   = 16,        // scope: PRODUCT
  PRODUCT_ACCESS  = 17,        // scope: PRODUCT
  PRODUCT_STORE   = 18,        // scope: PRODUCT
  PRODUCT_VIEW    = 19,        // scope: PRODUCT
}

/**
 * Status information about the database backend.
 */
enum DBStatus {
  OK,                           // Everything is ok with the database.
  MISSING,                      // The database is missing.
  FAILED_TO_CONNECT,            // Failed to connect to the database.
  SCHEMA_MISMATCH_OK,           // Schema mismatch between the server and the database.
  SCHEMA_MISMATCH_NO,           // No automatic migration is available.
  SCHEMA_MISSING,               // Schema is missing from the database.
  SCHEMA_INIT_ERROR,            // Failed to create initial database schema.
  SCHEMA_UPGRADE_FAILED         // Failed to upgrade schema.
}

/**
 * Common token type identifying a background task.
 * (Main implementation for task management API is in tasks.thrift.)
 */
typedef string TaskToken;
