// ─────────────────────────────────────────────────────────────
//  Looker Studio Community Connector – Schema Definitions
//  Covers all platforms: Google Ads, Meta Ads, GA4,
//  LinkedIn Ads, Twitter Ads, and the Unified view.
// ─────────────────────────────────────────────────────────────

var cc = DataStudioApp.createCommunityConnector();
var fields = cc.getFields();
var types = cc.FieldType;
var aggregations = cc.AggregationType;

// ── Dimensions ────────────────────────────────────────────────

/** @return {Fields} */
function getSchema() {
  var f = cc.getFields();

  // Shared across all tables
  f.newDimension()
    .setId('date')
    .setName('Date')
    .setType(types.YEAR_MONTH_DAY);

  f.newDimension()
    .setId('platform')
    .setName('Platform')
    .setDescription('google_ads | meta_ads | google_analytics | linkedin_ads | twitter_ads')
    .setType(types.TEXT);

  f.newDimension()
    .setId('campaign_id')
    .setName('Campaign ID')
    .setType(types.TEXT);

  f.newDimension()
    .setId('campaign_name')
    .setName('Campaign Name')
    .setType(types.TEXT);

  // Platform-specific dimensions
  f.newDimension()
    .setId('ad_group_name')
    .setName('Ad Group / Ad Set Name')
    .setType(types.TEXT);

  f.newDimension()
    .setId('ad_name')
    .setName('Ad Name')
    .setType(types.TEXT);

  f.newDimension()
    .setId('device')
    .setName('Device')
    .setType(types.TEXT);

  f.newDimension()
    .setId('network_type')
    .setName('Network Type')
    .setType(types.TEXT);

  f.newDimension()
    .setId('source')
    .setName('Source')
    .setType(types.TEXT);

  f.newDimension()
    .setId('medium')
    .setName('Medium')
    .setType(types.TEXT);

  f.newDimension()
    .setId('country')
    .setName('Country')
    .setType(types.TEXT);

  // ── Metrics ────────────────────────────────────────────────

  f.newMetric()
    .setId('impressions')
    .setName('Impressions')
    .setType(types.NUMBER)
    .setAggregation(aggregations.SUM);

  f.newMetric()
    .setId('clicks')
    .setName('Clicks')
    .setType(types.NUMBER)
    .setAggregation(aggregations.SUM);

  f.newMetric()
    .setId('spend')
    .setName('Spend ($)')
    .setType(types.CURRENCY_USD)
    .setAggregation(aggregations.SUM);

  f.newMetric()
    .setId('conversions')
    .setName('Conversions')
    .setType(types.NUMBER)
    .setAggregation(aggregations.SUM);

  f.newMetric()
    .setId('conversions_value')
    .setName('Conversion Value ($)')
    .setType(types.CURRENCY_USD)
    .setAggregation(aggregations.SUM);

  f.newMetric()
    .setId('reach')
    .setName('Reach')
    .setType(types.NUMBER)
    .setAggregation(aggregations.SUM);

  f.newMetric()
    .setId('video_views')
    .setName('Video Views')
    .setType(types.NUMBER)
    .setAggregation(aggregations.SUM);

  f.newMetric()
    .setId('engagements')
    .setName('Engagements')
    .setType(types.NUMBER)
    .setAggregation(aggregations.SUM);

  f.newMetric()
    .setId('leads')
    .setName('Leads')
    .setType(types.NUMBER)
    .setAggregation(aggregations.SUM);

  // ── Calculated / Derived Metrics ───────────────────────────

  f.newMetric()
    .setId('ctr')
    .setName('CTR')
    .setFormula('SUM($clicks) / SUM($impressions)')
    .setType(types.PERCENT)
    .setAggregation(aggregations.AUTO);

  f.newMetric()
    .setId('cpc')
    .setName('CPC ($)')
    .setFormula('SUM($spend) / SUM($clicks)')
    .setType(types.CURRENCY_USD)
    .setAggregation(aggregations.AUTO);

  f.newMetric()
    .setId('cpa')
    .setName('CPA ($)')
    .setFormula('SUM($spend) / SUM($conversions)')
    .setType(types.CURRENCY_USD)
    .setAggregation(aggregations.AUTO);

  f.newMetric()
    .setId('roas')
    .setName('ROAS')
    .setFormula('SUM($conversions_value) / SUM($spend)')
    .setType(types.NUMBER)
    .setAggregation(aggregations.AUTO);

  f.newMetric()
    .setId('cpm')
    .setName('CPM ($)')
    .setFormula('(SUM($spend) / SUM($impressions)) * 1000')
    .setType(types.CURRENCY_USD)
    .setAggregation(aggregations.AUTO);

  // GA4-specific
  f.newMetric()
    .setId('sessions')
    .setName('Sessions')
    .setType(types.NUMBER)
    .setAggregation(aggregations.SUM);

  f.newMetric()
    .setId('total_users')
    .setName('Total Users')
    .setType(types.NUMBER)
    .setAggregation(aggregations.SUM);

  f.newMetric()
    .setId('new_users')
    .setName('New Users')
    .setType(types.NUMBER)
    .setAggregation(aggregations.SUM);

  f.newMetric()
    .setId('bounce_rate')
    .setName('Bounce Rate')
    .setType(types.PERCENT)
    .setAggregation(aggregations.AVG);

  f.newMetric()
    .setId('avg_session_duration')
    .setName('Avg. Session Duration (s)')
    .setType(types.DURATION)
    .setAggregation(aggregations.AVG);

  f.newMetric()
    .setId('pageviews')
    .setName('Pageviews')
    .setType(types.NUMBER)
    .setAggregation(aggregations.SUM);

  f.newMetric()
    .setId('revenue')
    .setName('Revenue ($)')
    .setType(types.CURRENCY_USD)
    .setAggregation(aggregations.SUM);

  return f;
}
