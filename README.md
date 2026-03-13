# Tokyo DisneySea Wait Time Analyzer

Fetches historical wait times from Queue-Times.com, averages them over the past 7 days, and exports a CSV for visualization.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

```bash
python disney_wait_times.py          # fetch data → outputs CSV
python disney_wait_times.py --list   # list all ride IDs for a park
```

Open `disney_chart.html` in a browser and drag in the CSV to view the chart.

## Configuration

Edit `CONFIG` at the top of `disney_wait_times.py`:

| Key | Description |
|-----|-------------|
| `park_id` | `274` = Disneyland, `275` = DisneySea |
| `days_back` | How many past days to fetch |
| `time_precision_minutes` | Bucket size in minutes |
| `rides` | List of rides to track |
| `dpa_cutoff` | After 12:00, wait times below this value are treated as DPA-only and ignored. Set `None` to disable. |