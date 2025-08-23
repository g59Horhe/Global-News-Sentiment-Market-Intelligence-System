# News Sentiment Analysis System

A comprehensive news sentiment analysis system using mixed scraping methods (Selenium + Requests) to collect and analyze sentiment from major international news sources.

## Features

- **Mixed Method Scraping**: Combines Selenium for dynamic content and Requests for static content
- **8 News Sources**: BBC, Reuters, Guardian, CNN, Al Jazeera, NPR, Deutsche Welle, Washington Post  
- **Advanced Sentiment Analysis**: NLTK-based sentiment scoring with keyword extraction
- **Comprehensive Visualizations**: 12-panel dashboard with method comparison
- **Tableau Integration**: Export-ready datasets for advanced analytics
- **Database Storage**: SQLite database with method tracking

## Quick Start

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Install ChromeDriver for Selenium
4. Run: `python src/main.py`

## Project Structure

- **Selenium Sources**: Reuters, CNN, Washington Post, Deutsche Welle
- **Requests Sources**: BBC, Guardian, Al Jazeera, NPR
- **Output**: SQLite database, visualizations, Tableau-ready CSV files

## Data Science Applications

Perfect for:
- Sentiment analysis research
- Web scraping methodology comparison
- Media bias analysis
- Market sentiment tracking
- Academic capstone projects

## Requirements

- Python 3.7+
- ChromeDriver (for Selenium)
- See requirements.txt for full dependencies

## License

MIT License - see LICENSE file for details
