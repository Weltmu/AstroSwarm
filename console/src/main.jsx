import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import './tokens.css';
import './styles.css';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 40, color: '#dfe8ff', fontFamily: 'Inter, sans-serif' }}>
          <h2>页面出错了</h2>
          <pre style={{ whiteSpace: 'pre-wrap', color: '#f59e0b' }}>
            {String(this.state.error && this.state.error.message)}
          </pre>
          <button
            style={{
              marginTop: 16,
              padding: '9px 18px',
              borderRadius: 10,
              border: 'none',
              background: '#56d8ff',
              color: '#06121f',
              fontWeight: 700,
              cursor: 'pointer',
            }}
            onClick={() => window.location.reload()}
          >
            重新加载
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

createRoot(document.getElementById('root')).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>,
);
