#!/usr/bin/env python3
"""
Basic Usage Example - News Sentiment Analysis System
Shows how to run a simple news collection and analysis
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import FastSeleniumNewsScraper, SeleniumSentimentAnalyzer

def basic_example():
    """Basic example of collecting and analyzing news"""
    print("📰 Basic News Sentiment Analysis Example")
    print("=" * 50)
    
    # Initialize the scraper with conservative settings for demo
    scraper = FastSeleniumNewsScraper(
        max_articles_per_source=10,  # Small number for demo
        headless=True,               # Run in background
        max_workers=3               # Fewer workers for stability
    )
    
    try:
        print("🚀 Starting news collection...")
        articles = scraper.scrape_all_sources_fast()
        
        if articles:
            print(f"\n✅ Collected {len(articles)} articles")
            
            # Show some sample articles
            print("\n📄 Sample Articles:")
            for i, article in enumerate(articles[:3]):
                print(f"{i+1}. {article['title'][:80]}...")
                print(f"   Source: {article['source'].upper()}")
                print(f"   Sentiment: {article['sentiment_label']} ({article['sentiment_score']:.3f})")
                print()
            
            # Basic analysis
            positive_count = sum(1 for a in articles if a['sentiment_label'] == 'positive')
            negative_count = sum(1 for a in articles if a['sentiment_label'] == 'negative')
            neutral_count = sum(1 for a in articles if a['sentiment_label'] == 'neutral')
            
            print("📊 Sentiment Summary:")
            print(f"   😊 Positive: {positive_count} articles")
            print(f"   😔 Negative: {negative_count} articles") 
            print(f"   😐 Neutral: {neutral_count} articles")
            
        else:
            print("❌ No articles collected")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        scraper.cleanup()

if __name__ == "__main__":
    basic_example()
