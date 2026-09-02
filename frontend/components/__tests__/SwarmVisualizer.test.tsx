import React from 'react';
import { render, screen } from '@testing-library/react';
import { SwarmVisualizer } from '../SwarmVisualizer';

// Dashboard punch list, Round 2 (2 Sep 2026): SwarmVisualizer only has a
// genuinely specialized view for 3 of the swarm's many agents (Analyst #04,
// Forecaster #07, Strategist #15). Every other routed agent used to fall
// through to a permanent-looking "Awaiting specialized agent rendering..."
// placeholder, rendered right below CognitiveSearchBar's own already-complete
// answer for that same result -- read as a stuck/broken secondary widget.
// Fix: render nothing when there's no specialized view. These tests guard
// both directions -- the fixed case (no placeholder, no visible panel at
// all for an unhandled agent) and the still-working case (the 3 agents that
// do have a real view still render one).

function makeResult(workerAgentName: string, rawArtifacts?: Record<string, unknown>) {
  return {
    query: 'test query',
    synthesized_insight: 'Some synthesized answer text.',
    agent_breakdown: [
      { agent_name: 'Orchestrator Agent #00', domain: 'Routing', output_summary: 'Routed the query.' },
      { agent_name: workerAgentName, domain: 'Test Domain', output_summary: 'Did the work.', raw_artifacts: rawArtifacts },
    ],
    confidence_score: 0.99,
    status: 'SUCCESS',
  };
}

describe('SwarmVisualizer', () => {
  it('renders nothing when data is null', () => {
    const { container } = render(<SwarmVisualizer data={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when only the orchestrator agent is present (no worker agent)', () => {
    const data = {
      query: 'test query',
      synthesized_insight: 'answer',
      agent_breakdown: [{ agent_name: 'Orchestrator Agent #00', domain: 'Routing', output_summary: 'Routed.' }],
      confidence_score: 0.99,
      status: 'SUCCESS',
    };
    const { container } = render(<SwarmVisualizer data={data} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing -- not the old placeholder -- for an agent with no specialized view (e.g. Ops Shield #09)', () => {
    const { container } = render(<SwarmVisualizer data={makeResult('Ops Shield (Agent #09)')} />);
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText(/Awaiting specialized agent rendering/i)).not.toBeInTheDocument();
  });

  it('renders nothing for another unhandled agent (External Telemetry Scout #12)', () => {
    const { container } = render(<SwarmVisualizer data={makeResult('External Telemetry Scout (Agent #12)')} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('still renders the Analyst data table for Agent #04', () => {
    render(
      <SwarmVisualizer
        data={makeResult('Data Engineer (Agent #04)', { results: [{ month: 'Jan', total: 100 }] })}
      />
    );
    expect(screen.getByText(/Routed via/)).toBeInTheDocument();
    expect(screen.getByText('Data Engineer (Agent #04)')).toBeInTheDocument();
    expect(screen.getByText('month')).toBeInTheDocument();
  });

  it('still renders the Strategist advisory card for Agent #15', () => {
    render(<SwarmVisualizer data={makeResult('SaaS Strategist (Agent #15)')} />);
    expect(screen.getByText('Executive Strategic Advisory')).toBeInTheDocument();
    expect(screen.getByText('Some synthesized answer text.')).toBeInTheDocument();
  });

  it('still renders the Forecaster chart for Agent #07', () => {
    render(<SwarmVisualizer data={makeResult('Predictive Forecaster (Agent #07)', { model_type: 'ARIMA' })} />);
    expect(screen.getByText(/Prediction Model:/)).toBeInTheDocument();
  });
});
