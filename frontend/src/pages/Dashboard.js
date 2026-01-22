import { useState, useEffect } from 'react';
import axios from 'axios';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Loader2, FileText, GitPullRequest, MessageSquare, Users, Component, AlertTriangle, Sparkles } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const Dashboard = () => {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);

  const fetchStats = async () => {
    try {
      const response = await axios.get(`${API}/stats`);
      setStats(response.data);
    } catch (error) {
      console.error('Error fetching stats:', error);
    } finally {
      setLoading(false);
    }
  };

  const generateMockData = async () => {
    setGenerating(true);
    try {
      await axios.post(`${API}/mock/generate-multiple?count=5`);
      await fetchStats();
      alert('Mock data generated successfully!');
    } catch (error) {
      console.error('Error generating mock data:', error);
      alert('Error generating mock data');
    } finally {
      setGenerating(false);
    }
  };

  useEffect(() => {
    fetchStats();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    );
  }

  const statCards = [
    { icon: FileText, label: 'ScopeDocs', value: stats?.scopedocs || 0, color: 'text-blue-500' },
    { icon: GitPullRequest, label: 'Pull Requests', value: stats?.pull_requests || 0, color: 'text-purple-500' },
    { icon: MessageSquare, label: 'Conversations', value: stats?.conversations || 0, color: 'text-green-500' },
    { icon: Users, label: 'Work Items', value: stats?.work_items || 0, color: 'text-orange-500' },
    { icon: Component, label: 'Components', value: stats?.components || 0, color: 'text-cyan-500' },
    { icon: AlertTriangle, label: 'Drift Alerts', value: stats?.drift_alerts || 0, color: 'text-red-500' },
  ];

  return (
    <div className="space-y-8">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-4xl font-bold" data-testid="dashboard-title">ScopeDocs Dashboard</h1>
          <p className="text-muted-foreground mt-2">Living documentation from your workflow</p>
        </div>
        <Button 
          onClick={generateMockData} 
          disabled={generating}
          data-testid="generate-mock-data-btn"
        >
          {generating ? (
            <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Generating...</>
          ) : (
            <><Sparkles className="mr-2 h-4 w-4" /> Generate Mock Data</>
          )}
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {statCards.map((stat) => {
          const Icon = stat.icon;
          return (
            <Card key={stat.label} data-testid={`stat-card-${stat.label.toLowerCase().replace(/\s+/g, '-')}`}>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">{stat.label}</CardTitle>
                <Icon className={`h-4 w-4 ${stat.color}`} />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{stat.value}</div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {stats && (stats.work_items === 0 && stats.scopedocs === 0) && (
        <Card className="border-dashed" data-testid="getting-started-card">
          <CardHeader>
            <CardTitle>🚀 Getting Started</CardTitle>
            <CardDescription>
              Generate mock data to explore all features of ScopeDocs
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Click the "Generate Mock Data" button above to create sample:
            </p>
            <ul className="list-disc list-inside space-y-2 text-sm">
              <li>Linear work items from different projects</li>
              <li>GitHub pull requests with file changes</li>
              <li>Slack conversations with decisions</li>
              <li>Component ownership information</li>
              <li>Relationship mappings between artifacts</li>
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

export default Dashboard;