import sys, os, argparse, logging, logging.handlers
import sqlite3
import csv
import re
import json
import locale, datetime
import dateparser

def sanitizeValue(row, account_type, field_name, config):
  input_value = row[config["import_settings"][account_type][field_name]['index']]
  if config["import_settings"][account_type][field_name]['trim']:
    return re.sub(r'[^A-Za-z0-9\s\-\.]', '', input_value).strip()
  else:
    return input_value
    
    
def loadCsv(filename):
  with open(filename, 'r') as csvfile:
    sample = csvfile.read(1024)
    has_header = csv.Sniffer().has_header(sample)
    deduced_dialect = csv.Sniffer().sniff(sample)
    deduced_dialect.skipinitialspace = True

  logging.info("Opening file %s" % filename)
  csv_rows = []
  with open(filename, 'r') as csvfile:
    reader = csv.reader(csvfile, deduced_dialect)
    if has_header:
      next(reader)
    for row in reader:
      csv_rows.append(row)
      
  return csv_rows
  
  
def loadDataConfig(dirname, config):
   try:
     pathname = os.path.join(dirname,config['data_config_file'])
     file = open(pathname, 'r')
     dataconfig = json.load(file)
     config['import_settings'] = dataconfig['import_settings']
     config['expense_categories'] = dataconfig['expense_categories']
   except:
     logging.info("Failed loading data config from %s" % pathname)
     return False
   else:
     logging.info("Loaded data config from %s" % pathname)
     return True
  
  
def gobbleTypedReport(filename, account_type, dbconn, config):
  columnindex_date = config["import_settings"][account_type]['column_date']['index']
  columnindex_description = config["import_settings"][account_type]['column_description']['index']

  source_rows = loadCsv(filename)
  # Sort by date+description if duplicate resolution is enabled
  if config["fix_duplicates_on_import"]:
    source_rows.sort(key=lambda x: x[columnindex_date]+x[columnindex_description])

  numadded = 0
  numskipped = 0
  previous_row = []
  duplicate_index = 1
  for row in source_rows:
    # Make duplicate source records unique if duplicate resolution is enabled
    if config["fix_duplicates_on_import"] and row == previous_row:
      row[columnindex_description] += (' %d' % duplicate_index);
      duplicate_index += duplicate_index;
    else:
      previous_row = row
      duplicate_index = 1
        
    try:
      column_values = [
        dateparser.parse(date_string=sanitizeValue(row, account_type, 'column_date', config), locales=[config["locale"]]),
        sanitizeValue(row, account_type, 'column_description', config),
        locale.atof(sanitizeValue(row, account_type, 'column_amount', config)),
        account_type]
      with dbconn:
        dbconn.execute('''INSERT INTO transactions (date,description,amount,account) VALUES(?,?,?,?)''', column_values)
    except sqlite3.IntegrityError:
      logging.warning("Failed inserting row, possible duplicate: %s" % column_values)
      numskipped += 1
    else:
      numadded += 1
  dbconn.commit()
  logging.info("Finished reading %s: added %d rows, skipped %d rows" % (filename, numadded, numskipped))
  
  
def gobbleReport(filename, dbconn, config):
  if not 'import_settings' in config:
    logging.error("Import settings not defined. Make sure a data config file (%s) exists in the script directory" % config['data_config_file'])
    return
    
  account_type = None
  for key in config["import_settings"]:
    if re.search(config["import_settings"][key]['filename_regexp'],filename):
      account_type = key
      break
  if account_type is None:
    logging.error("Cannot determine account type based on filename: %s" % filename)
    return
  
  gobbleTypedReport(filename, account_type, dbconn, config)
  
  
def gobbleDirectory(dirname, dbconn, config):
  loadDataConfig(dirname, config)
  
  if not 'import_settings' in config:
    logging.error("Import settings not defined. Make sure a data config file (%s) exists either in the script directory, or in the target directory" % config['data_config_file'])
    return
    
  for entry in os.scandir(dirname):
    for account_type in config["import_settings"]:
      if re.search(config["import_settings"][account_type]['filename_regexp'],entry.name):
        gobbleTypedReport(entry.path, account_type, dbconn, config)
  
  
def gobbleReportList(filenames, dbconn, config):
  for filename in filenames:
    if os.path.isdir(filename):
      gobbleDirectory(filename, dbconn, config)
    else:
      gobbleReport(filename, dbconn, config)
  logging.info("Finished reading %s" % filenames)

  
def matchCategory(description, all_categories):
  for category in all_categories:
    for row in all_categories[category]['regexps']:
      if re.search(row,description,re.IGNORECASE):
        return category


def categorizeExpenses(dbconn, config, force):
  logging.info("Categorizing expenses (%s)" % force)
  
  if force:
    cursor = dbconn.execute('SELECT * from transactions')
  else:
    cursor = dbconn.execute('SELECT * from transactions where category IS NULL OR category=?', (config["unmatched_category"],))
  
  while True:
    row=cursor.fetchone()
    if not row:
      break

    category = matchCategory(row['description'],config['expense_categories'])
    if category is None:
      category = config["unmatched_category"]
      
    dbconn.execute('UPDATE transactions SET category = ? WHERE date=? AND description=? AND amount=?', (category, row['date'], row['description'], row['amount']))
      
  dbconn.commit()


def exportToCsv(dbconn, config, outputFile):
  logging.info("Saving transactions to CSV: %s" % outputFile)
  
  with open(outputFile,'w', newline='') as csvfile:
    writer = csv.writer(csvfile, delimiter=config["csv_output_delimiter"])
    transactionRows = dbconn.execute('SELECT * from transactions ORDER BY date')
  
    for row in transactionRows:
      writer.writerow(row)

def exportToJs(dbconn, config, outputFile):
  logging.info("Saving transactions to JS: %s" % outputFile)
  
  with open(config['js_template'],'r') as templatefile:
    templatedata = templatefile.read()
  
  with open(outputFile,'w', newline='') as outfile:
    outfile.write(templatedata)
    
    outfile.write("window.categoryProps = new Map([\n")
    for category in config['expense_categories']:
      outfile.write("\t[\"%s\",\t{ color:%s,	group:%d} ],\n" % (category, config['expense_categories'][category]['color'], config['expense_categories'][category]['group']));
    outfile.write("]);\n")
  
    outfile.write("window.expenses = [\n")
    
    transactionRows = dbconn.execute('SELECT * from transactions ORDER BY date')
  
    for row in transactionRows:
      outfile.write("\t[{date: \"%s\", description: \"%s\", amount: %f, account: \"%s\",category: \"%s\", categorygroup: %d}],\n" % (row['date'],row['description'],row['amount'], row['account'], row['category'], config['expense_categories'][row['category']]['group']))

    outfile.write("];")

def main(args, loglevel):
  logging.basicConfig(format="%(asctime)-15s %(levelname)s: %(message)s", level=loglevel)
  
  logFileFormatter = logging.Formatter("%(asctime)-15s %(levelname)s: %(message)s");
  logHandler = logging.handlers.RotatingFileHandler('report_gobbler.log',maxBytes=1024*1024,backupCount=5)
  logHandler.setLevel(logging.INFO)
  logHandler.setFormatter(logFileFormatter)
  logging.getLogger().addHandler(logHandler)
  
  logging.info("============================== report_gobbler start ==============================")
  logging.info("Arguments: %s" % args)
  
  with open("config.json") as json_data_file:
    config = json.load(json_data_file)
    
  loadDataConfig("", config)
  
  locale.setlocale(locale.LC_ALL, config["locale"])
  
  dbconn = sqlite3.connect(config["database_file"], detect_types=sqlite3.PARSE_DECLTYPES)
  dbconn.row_factory = sqlite3.Row
  
  try:
    with dbconn:
      dbconn.execute('''CREATE TABLE transactions
      (date TIMESTAMP, description TEXT, amount REAL, account VARCHAR, category VARCHAR, PRIMARY KEY(date, description, amount))''')
      dbconn.commit()
  except sqlite3.Error as e:
    logging.info("Couldn't create transactions table, assuming it already exists:")
    logging.info(e)
  
  if args.filestogobble is not None:
    gobbleReportList(args.filestogobble, dbconn, config)
    categorizeExpenses(dbconn, config, False)
  
  if args.output is not None:
    exportToCsv(dbconn, config, args.output)
    
  if args.savetojs is not None:
    exportToJs(dbconn, config, args.savetojs)
  
  dbconn.close()
  logging.info("============================== report_gobbler end ==============================")
 

if __name__ == '__main__':
  parser = argparse.ArgumentParser( 
                                    description = "Does a thing to some stuff.",
                                    epilog = "As an alternative to the commandline, params can be placed in a file, one per line, and specified on the commandline like '%(prog)s @params.conf'.",
                                    fromfile_prefix_chars = '@' )
  # TODO Specify your real parameters here.
  parser.add_argument(
                      "filestogobble",
                      nargs = '*',
                      help = "parse one or more CSV transaction reports and store the transactions in the database",
                      metavar = "TransactionReports")
  parser.add_argument(
                      "-v",
                      "--verbose",
                      help = "increase output verbosity",
                      action = "store_true")
  parser.add_argument(
                      "-o",
                      "--output",
                      help = "save all transactions to a specified CSV file")
  parser.add_argument(
                      "-j",
                      "--savetojs",
                      help = "save all transactions to a specified JS file")
  args = parser.parse_args()
  
  # Setup logging
  if args.verbose:
    loglevel = logging.DEBUG
  else:
    loglevel = logging.INFO
  
  main(args, loglevel)