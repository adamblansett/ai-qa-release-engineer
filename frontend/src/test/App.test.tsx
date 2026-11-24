import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from '../App';

describe('AI QA & Release Engineer starter workspace', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders planned capabilities and live API health status', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        status: 'ok',
        service: 'ai-qa-release-engineer',
        app_name: 'AI QA & Release Engineer',
        version: '0.1.0',
        environment: 'test',
        llm_provider: 'mock',
      }),
    });
    vi.stubGlobal('fetch', mockFetch);

    render(<App />);

    expect(screen.getByRole('heading', { name: 'AI QA & Release Engineer' })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/API Healthy \(mock\)/i)).toBeInTheDocument();
    });
    expect(mockFetch).toHaveBeenCalledWith('/api/v1/health');
  });
});
