/**
 * Costing pipeline — Google Apps Script setup utility.
 *
 * Optional companion to the Django app. Run these from script.google.com in the
 * SAME Google account that owns the Drive. They create exactly the same storage
 * (Drive folder tree) and database (control spreadsheet) the Python app uses, so
 * you can bootstrap without the OAuth flow, or run monthly setup by hand.
 *
 * Usage:
 *   1) Run setupCosting()      -> creates the "Costing" root folder + "Costing App DB"
 *                                 spreadsheet; logs their ids (put them in settings.py).
 *   2) Run newPeriod()         -> edit PERIOD_NAME below first; builds the folder tree
 *                                 and adds a Periods row.
 */

var ROOT_NAME = 'Costing';
var DB_NAME = 'Costing App DB';
var PERIOD_NAME = '2. Jun 26 YTD';   // <-- edit before running newPeriod()

// Folder tree created for every period (mirrors the source package exactly).
var FOLDER_TREE = {
  '01. ERP Source File': {},
  '02. Sales, Cinsumption and Productiond data File': {},
  '03. Expense': {
    'Expense not routed though JVR': {
      'APTR': {},
      'Depreciation': {}
    }
  },
  '04. Other data': {
    'Labour hour': {},
    'Packing Routed through BOM': {}
  }
};

// Database tables: tab name -> header columns.
var TABLES = {
  'Periods': ['period_id', 'name', 'folder_id', 'status', 'created_at'],
  'SourceFiles': ['period_id', 'file_type', 'name', 'drive_file_id', 'sheet_id', 'status', 'uploaded_at'],
  'DataFiles': ['period_id', 'data_key', 'name', 'sheet_id', 'status', 'updated_at'],
  'RunLog': ['period_id', 'stage', 'status', 'message', 'at']
};

function getOrCreateFolder_(parent, name) {
  var it = parent.getFoldersByName(name);
  return it.hasNext() ? it.next() : parent.createFolder(name);
}

function getRoot_() {
  return getOrCreateFolder_(DriveApp.getRootFolder(), ROOT_NAME);
}

function setupCosting() {
  var root = getRoot_();
  Logger.log('Costing root folder id: ' + root.getId());

  // Create the control spreadsheet with all tabs + headers, then move to root.
  var ss = SpreadsheetApp.create(DB_NAME);
  var names = Object.keys(TABLES);
  for (var i = 0; i < names.length; i++) {
    var t = names[i];
    var sheet = (i === 0) ? ss.getSheets()[0].setName(t) : ss.insertSheet(t);
    sheet.getRange(1, 1, 1, TABLES[t].length).setValues([TABLES[t]]);
  }
  var file = DriveApp.getFileById(ss.getId());
  root.addFile(file);
  DriveApp.getRootFolder().removeFile(file);

  Logger.log('Control database sheet id: ' + ss.getId());
  Logger.log('Put these in settings.py:');
  Logger.log("  GOOGLE_COSTING_ROOT_FOLDER_ID = '" + root.getId() + "'");
  Logger.log("  GOOGLE_COSTING_DB_SHEET_ID = '" + ss.getId() + "'");
}

function buildTree_(parent, tree) {
  var out = {};
  var names = Object.keys(tree);
  for (var i = 0; i < names.length; i++) {
    var child = getOrCreateFolder_(parent, names[i]);
    out[names[i]] = child.getId();
    var sub = tree[names[i]];
    if (Object.keys(sub).length) buildTree_(child, sub);
  }
  return out;
}

function newPeriod() {
  var root = getRoot_();
  var period = getOrCreateFolder_(root, PERIOD_NAME);
  buildTree_(period, FOLDER_TREE);
  Logger.log('Period folder id: ' + period.getId());

  // Append a Periods row to the control DB (finds it by name under root).
  var it = root.getFilesByName(DB_NAME);
  if (it.hasNext()) {
    var ss = SpreadsheetApp.open(it.next());
    var sheet = ss.getSheetByName('Periods');
    sheet.appendRow([period.getId(), PERIOD_NAME, period.getId(), 'open',
                     new Date().toISOString()]);
    Logger.log('Registered period in ' + DB_NAME);
  } else {
    Logger.log('Run setupCosting() first to create ' + DB_NAME + '.');
  }
}
