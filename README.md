# Where Is My Money?
## Personal Finances Spending Report with CSV Gobbler

If, like me, you are wondering where does your hard-earned money vanish to, perhaps this little tool will help you!

This is a yet another personal finances tool consisting of two parts:
* csv_bank_report_gobbler.py: a python script to parse bank transaction reports in a form of CSV files
* WhereIsMyMoney.html: an HTML page to present categorized transactions in a stacked bar chart

How it works:
![Operation Diagram](https://github.com/ilookha/whereismymoney/raw/main/diagram.png)

Resulting chart (using *sample_dataset*):
![](https://github.com/ilookha/whereismymoney/raw/main/screenshot.png)


# Usage
## 1. Gobble the CSV reports
```
python csv_bank_report_gobbler.py -j expenses_data.js sample_dataset
```
This command will:
1. Look for parser configuration inside *sample_dataset* directory (*data_config.json* by default)
1. Look for CSV reports that match parser configuration
1. For every row in each report:
    1. Categorise by matching description against known categories defined inside data_config
    1. Add a row to an sqlite database (*money.db* by default)
1. Save all db rows to a JavaScript array to be read by the visualizer (*expenses_data.js*)

## 2. Open the visualizer
```
WhereIsMyMoney.html
```
The visualizer will:
1. Store all rows in an AlaSQL database
1. Group expenses by month and by category, feeding them to a Charts.js stacked bar chart
