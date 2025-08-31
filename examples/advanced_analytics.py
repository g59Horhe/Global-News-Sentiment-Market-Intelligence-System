#!/usr/bin/env python3
"""
Advanced Analytics Example - Shows visualization and detailed analysis
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import SeleniumSentimentAnalyzer
import pandas as pd

def advanced_analytics_example():
    """Advanced example showing analytics and visualization"""
    print("📊 Advanced Analytics Example")
    print("=" * 50)
    
    # Initialize analyzer
    analyzer = SeleniumSentimentAnalyzer()
    
    try:
        # Get articles from database
        print("📚 Loading articles from database...")
        df = analyzer.get_articles_from_db(limit=200)
        
        if df.empty:
            print("❌ No articles found in database. Run main.py first!")
            return
        
        print(f"✅ Loaded {len(df)} articles")
        
        # Analyze trends
        print("\n📈 Analyzing sentiment trends...")
        trends = analyzer.analyze_sentiment_trends(df)
        
        # Display insights
        print(f"\n🎯 Analysis Results:")
        print(f"   📊 Total Articles: {trends['total_articles']:,}")
        print(f"   📅 Date Range: {trends['date_range']['start'].strftime('%Y-%m-%d')} to {trends['date_range']['end'].strftime('%Y-%m-%d')}")
        print(f"   📝 Avg Content Length: {trends['avg_content_length']:.0f} characters")
        
        print(f"\n📰 Top Sources by Sentiment:")
        source_sentiment = trends['source_sentiment'].sort_values(ascending=False)
        for source, sentiment in source_sentiment.items():
            emoji = "😊" if sentiment > 0.1 else "😔" if sentiment < -0.1 else "😐"
            print(f"   {emoji} {source.upper():10}: {sentiment:+.3f}")
        
        print(f"\n📂 Top Categories:")
        category_sentiment = trends['category_sentiment'].sort_values(ascending=False)
        for category, sentiment in category_sentiment.head().items():
            emoji = "😊" if sentiment > 0.1 else "😔" if sentiment < -0.1 else "😐"
            print(f"   {emoji} {category.title():12}: {sentiment:+.3f}")
        
        # Generate visualizations
        print(f"\n🎨 Creating visualizations...")
        analyzer.create_visualizations(df, 'advanced_analysis_dashboard.png')
        
        # Generate report
        print(f"\n📋 Generating detailed report...")
        report = analyzer.generate_summary_report(df)
        
        with open('advanced_analysis_report.txt', 'w', encoding='utf-8') as f:
            f.write(report)
        
        print("✅ Advanced analysis completed!")
        print("📄 Files generated:")
        print("   • advanced_analysis_dashboard.png")
        print("   • advanced_analysis_report.txt")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        analyzer.close()

if __name__ == "__main__":
    advanced_analytics_example()
