// ─────────────────────────────────────────────────────────────────────────────
//  Looker Studio Community Connector
//  Multi-Platform Marketing: Google Ads · Meta Ads · GA4 · LinkedIn · Twitter
//
//  Deploy via Google Apps Script (clasp or script.google.com).
//  Data is read from the BigQuery tables populated by the Python pipeline.
// ─────────────────────────────────────────────────────────────────────────────

var cc = DataStudioApp.createCommunityConnector();

// ── Auth ──────────────────────────────────────────────────────────────────────

function getAuthType() {
  return cc
    .newAuthTypeResponse()
    .setAuthType(cc.AuthType.OAUTH2)
    .build();
}

function getOAuthService() {
  return OAuth2.createService('BigQueryOAuth')
    .setAuthorizationBaseUrl('https://accounts.google.com/o/oauth2/auth')
    .setTokenUrl('https://oauth2.googleapis.com/token')
    .setClientId(getConfig_().oauthClientId)
    .setClientSecret(getConfig_().oauthClientSecret)
    .setCallbackFunction('authCallback')
    .setPropertyStore(PropertiesService.getUserProperties())
    .setScope([
      'https://www.googleapis.com/auth/bigquery.readonly',
      'https://www.googleapis.com/auth/userinfo.email',
    ].join(' '));
}

function authCallback(request) {
  var service = getOAuthService();
  var authorized = service.handleCallback(request);
  return HtmlService.createHtmlOutput(
    authorized ? 'Authorization successful! Close this tab.' : 'Authorization failed.'
  );
}

function isAuthValid() {
  return getOAuthService().hasAccess();
}

function resetAuth() {
  getOAuthService().reset();
}

function get3PAuthorizationUrls() {
  return getOAuthService().getAuthorizationUrl();
}

// ── Config ────────────────────────────────────────────────────────────────────

/**
 * Returns the connector configuration UI shown in Looker Studio.
 */
function getConfig(request) {
  var config = cc.getConfig();

  config
    .newInfo()
    .setId('instructions')
    .setText(
      'Connect your Google Ads, Meta Ads, GA4, LinkedIn Ads and Twitter Ads ' +
      'data via a unified BigQuery dataset. Fill in the fields below.'
    );

  config
    .newTextInput()
    .setId('bq_project_id')
    .setName('BigQuery Project ID')
    .setHelpText('GCP project that contains the marketing dataset.')
    .setPlaceholder('my-gcp-project');

  config
    .newTextInput()
    .setId('bq_dataset_id')
    .setName('BigQuery Dataset ID')
    .setHelpText('Dataset created by the Python pipeline (default: looker_studio_integration).')
    .setPlaceholder('looker_studio_integration');

  config
    .newSelectSingle()
    .setId('table')
    .setName('Data Table')
    .setHelpText('Choose which platform table (or the unified view) to display.')
    .addOption(config.newOptionBuilder().setLabel('Unified (all platforms)').setValue('unified_performance'))
    .addOption(config.newOptionBuilder().setLabel('Google Ads').setValue('google_ads_performance'))
    .addOption(config.newOptionBuilder().setLabel('Meta Ads (Facebook/Instagram)').setValue('meta_ads_performance'))
    .addOption(config.newOptionBuilder().setLabel('Google Analytics 4').setValue('ga4_performance'))
    .addOption(config.newOptionBuilder().setLabel('LinkedIn Ads').setValue('linkedin_ads_performance'))
    .addOption(config.newOptionBuilder().setLabel('Twitter / X Ads').setValue('twitter_ads_performance'));

  config
    .newTextInput()
    .setId('cache_duration')
    .setName('Cache Duration (seconds)')
    .setHelpText('How long to cache query results. Default: 3600.')
    .setPlaceholder('3600');

  config.setDateRangeRequired(true);

  return config.build();
}

// ── Schema ────────────────────────────────────────────────────────────────────

function getSchema(request) {
  return { schema: getSchema_().build() };
}

/** Returns the Fields object matching the selected table. */
function getSchema_() {
  return getSchema(); // delegates to schema.js
}

// ── Data ──────────────────────────────────────────────────────────────────────

function getData(request) {
  var configParams = request.configData;
  var projectId   = configParams.bq_project_id;
  var datasetId   = configParams.bq_dataset_id   || 'looker_studio_integration';
  var tableName   = configParams.table            || 'unified_performance';

  var startDate = request.dateRange.startDate;   // YYYY-MM-DD
  var endDate   = request.dateRange.endDate;

  // Build the BigQuery SQL
  var requestedFields = request.fields.map(function(f) { return f.name; });
  var columnList = requestedFields.join(', ');

  var sql = Utilities.formatString(
    'SELECT %s ' +
    'FROM `%s.%s.%s` ' +
    "WHERE date BETWEEN '%s' AND '%s' " +
    'ORDER BY date ASC',
    columnList, projectId, datasetId, tableName, startDate, endDate
  );

  // Check cache first
  var cacheKey = Utilities.computeDigest(
    Utilities.DigestAlgorithm.MD5,
    sql
  ).join('');
  var cache = CacheService.getUserCache();
  var cached = cache.get(cacheKey);
  if (cached) {
    return JSON.parse(cached);
  }

  // Run BigQuery query
  var token = getOAuthService().getAccessToken();
  var response = runBigQueryQuery_(projectId, sql, token);
  var rows = transformBigQueryResults_(response, requestedFields);

  var schema = getSchema_().build().filter(function(field) {
    return requestedFields.indexOf(field.name) !== -1;
  });

  var result = { schema: schema, rows: rows };

  // Cache result
  var cacheDuration = parseInt(configParams.cache_duration || '3600', 10);
  cache.put(cacheKey, JSON.stringify(result), cacheDuration);

  return result;
}

// ── BigQuery helpers ──────────────────────────────────────────────────────────

/**
 * Runs a synchronous BigQuery query via the REST API.
 *
 * @param {string} projectId
 * @param {string} sql
 * @param {string} accessToken
 * @return {Object} BigQuery query response JSON
 */
function runBigQueryQuery_(projectId, sql, accessToken) {
  var url = Utilities.formatString(
    'https://bigquery.googleapis.com/bigquery/v2/projects/%s/queries',
    projectId
  );

  var payload = JSON.stringify({
    query: sql,
    useLegacySql: false,
    timeoutMs: 30000,
    maxResults: 100000,
  });

  var options = {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + accessToken },
    payload: payload,
    muteHttpExceptions: true,
  };

  var response = UrlFetchApp.fetch(url, options);
  var result = JSON.parse(response.getContentText());

  if (result.error) {
    cc.newUserError()
      .setText('BigQuery error: ' + result.error.message)
      .throwException();
  }

  // Handle paginated results
  var rows = result.rows || [];
  var pageToken = result.pageToken;

  while (pageToken) {
    var pageUrl = Utilities.formatString(
      'https://bigquery.googleapis.com/bigquery/v2/projects/%s/queries/%s?pageToken=%s',
      projectId, result.jobReference.jobId, pageToken
    );
    var pageResp = UrlFetchApp.fetch(pageUrl, {
      headers: { Authorization: 'Bearer ' + accessToken },
      muteHttpExceptions: true,
    });
    var pageResult = JSON.parse(pageResp.getContentText());
    rows = rows.concat(pageResult.rows || []);
    pageToken = pageResult.pageToken;
  }

  result.rows = rows;
  return result;
}

/**
 * Converts BigQuery row format to Looker Studio row format.
 *
 * BigQuery rows: [{ f: [{ v: '...' }, ...] }]
 * Looker Studio rows: [{ values: ['...', ...] }]
 */
function transformBigQueryResults_(bqResponse, requestedFields) {
  var schema = bqResponse.schema && bqResponse.schema.fields || [];
  var colIndex = {};
  schema.forEach(function(col, i) { colIndex[col.name] = i; });

  return (bqResponse.rows || []).map(function(row) {
    var values = requestedFields.map(function(fieldName) {
      var idx = colIndex[fieldName];
      if (idx === undefined) return null;
      var cell = row.f[idx];
      return cell ? cell.v : null;
    });
    return { values: values };
  });
}

// ── Misc ──────────────────────────────────────────────────────────────────────

function getConnectorInfo() {
  return cc
    .newGetConnectorInfoResponse()
    .setIsAdminUser(true)
    .build();
}

/**
 * Returns static connector config stored in Script Properties.
 * Set OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET in the Apps Script
 * project's Script Properties.
 */
function getConfig_() {
  var props = PropertiesService.getScriptProperties();
  return {
    oauthClientId:     props.getProperty('OAUTH_CLIENT_ID')     || '',
    oauthClientSecret: props.getProperty('OAUTH_CLIENT_SECRET') || '',
  };
}
