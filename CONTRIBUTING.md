# Contributing to News Sentiment Analysis System

Thank you for your interest in contributing! This document provides guidelines for contributing to the project.

## 🚀 Quick Start for Contributors

1. **Fork the repository**
2. **Clone your fork**: `git clone https://github.com/yourusername/news-sentiment-system.git`
3. **Create a branch**: `git checkout -b feature/your-feature-name`
4. **Make your changes**
5. **Test your changes**: `python main.py` and verify it works
6. **Commit**: `git commit -am 'Add some feature'`
7. **Push**: `git push origin feature/your-feature-name`
8. **Create a Pull Request**

## 📋 Types of Contributions

### 🐛 Bug Fixes
- Found a bug? Please create an issue first
- Include reproduction steps and system info
- Reference the issue in your PR

### ✨ New Features
- **News Sources**: Add support for new news websites
- **Analysis Methods**: Improve sentiment analysis algorithms
- **Visualizations**: Create new dashboard components
- **Performance**: Optimize scraping speed and reliability

### 📚 Documentation
- Improve README sections
- Add code comments
- Create tutorials and examples
- Update API documentation

### 🔧 Code Quality
- Add unit tests
- Improve error handling
- Optimize performance
- Enhance logging

## 💻 Development Setup

```bash
# Setup development environment
git clone https://github.com/yourusername/news-sentiment-system.git
cd news-sentiment-system
python -m venv news_env
source news_env/bin/activate  # Windows: news_env\Scripts\activate
pip install -r requirements.txt
python setup.py  # Verify installation
```

## 🧪 Testing Your Changes

Before submitting a PR, please test:

```bash
# Test basic functionality
python main.py

# Test Reuters optimization
python check_reuters_optimization.py

# Test data preparation
python prepare_tableau_data.py

# Run examples
python examples/basic_usage.py
python examples/advanced_analytics.py
```

## 📝 Code Style Guidelines

- **Python**: Follow PEP 8 style guidelines
- **Comments**: Use clear, concise comments for complex logic
- **Functions**: Keep functions focused on single responsibilities
- **Error Handling**: Use appropriate exception handling
- **Logging**: Use the existing logging system

### Adding New News Sources

When adding a new source, include:

```python
'newsource': {
    'base_urls': [
        'https://example.com/news',
        'https://example.com/world'
    ],
    'selectors': {
        'article_links': ['a[href*="/article/"]', '.story a'],
        'title': ['h1', '.headline'],
        'content': ['article p', '.content p'],
        'date': ['time[datetime]', '.date'],
        'author': ['.byline', '.author']
    }
}
```

## 🔍 Performance Guidelines

- Maintain collection rate of 8+ articles/minute
- Ensure 90%+ content extraction accuracy
- Test with multiple sources simultaneously
- Monitor memory usage during long runs

## 📊 Pull Request Guidelines

### PR Title Format
- `[FEATURE] Add support for Reuters optimization`
- `[BUG] Fix ChromeDriver initialization issue`
- `[DOCS] Update installation instructions`
- `[PERF] Improve parallel processing efficiency`

### PR Description Template
```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Performance improvement

## Testing
- [ ] Tested with all news sources
- [ ] Verified sentiment analysis accuracy
- [ ] Checked performance metrics
- [ ] Updated documentation

## Screenshots/Logs
(If applicable)
```

## 🚨 Reporting Issues

### Bug Reports
Use the bug report template and include:
- System information (OS, Python version, Chrome version)
- Reproduction steps
- Expected vs actual behavior
- Error logs and screenshots

### Performance Issues
- Include performance metrics before/after
- Specify which news sources are affected
- Provide system resource usage information

## 🎯 Priority Areas for Contribution

1. **🌐 New News Sources**: Add support for international news sites
2. **🧠 AI Enhancement**: Improve sentiment analysis with modern models
3. **📊 Analytics**: Add more visualization types and metrics
4. **🔧 Reliability**: Improve error handling and recovery
5. **📱 Interface**: Create web interface or API endpoints
6. **🌍 Internationalization**: Support for non-English news sources

## ⭐ Recognition

Contributors will be recognized in:
- README contributors section
- Release notes for significant contributions
- GitHub contributor graph

## 📞 Getting Help

- **Issues**: Create a GitHub issue for bugs or questions
- **Discussions**: Use GitHub Discussions for general questions
- **Email**: Contact maintainers for sensitive issues

Thank you for contributing to make news sentiment analysis better! 🚀
