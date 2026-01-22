import { useState, useEffect } from 'react';
import axios from 'axios';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Loader2, Users, Package } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const Ownership = () => {
  const [ownership, setOwnership] = useState(null);
  const [components, setComponents] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchOwnership = async () => {
    try {
      const [ownershipRes, componentsRes] = await Promise.all([
        axios.get(`${API}/ownership`),
        axios.get(`${API}/components`)
      ]);
      setOwnership(ownershipRes.data);
      setComponents(componentsRes.data);
    } catch (error) {
      console.error('Error fetching ownership:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOwnership();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-4xl font-bold" data-testid="ownership-title">Ownership</h1>
        <p className="text-muted-foreground mt-2">
          Component ownership tracked from CODEOWNERS and Linear teams
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card data-testid="stat-card-components">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Components</CardTitle>
            <Package className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{ownership?.total_components || 0}</div>
          </CardContent>
        </Card>

        <Card data-testid="stat-card-people">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total People</CardTitle>
            <Users className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{ownership?.total_people || 0}</div>
          </CardContent>
        </Card>

        <Card data-testid="stat-card-owners">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active Owners</CardTitle>
            <Users className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {ownership?.ownership_distribution ? Object.keys(ownership.ownership_distribution).length : 0}
            </div>
          </CardContent>
        </Card>
      </div>

      {ownership?.ownership_distribution && Object.keys(ownership.ownership_distribution).length > 0 && (
        <Card data-testid="ownership-distribution-card">
          <CardHeader>
            <CardTitle>Ownership Distribution</CardTitle>
            <CardDescription>
              Components owned by each person
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {Object.entries(ownership.ownership_distribution).map(([person, data]) => (
                <div key={person} className="flex items-center justify-between p-4 border rounded-lg" data-testid={`owner-item-${person.replace(/\s+/g, '-')}`}>
                  <div className="space-y-1">
                    <p className="font-medium">{person}</p>
                    {data.team && (
                      <Badge variant="secondary">
                        <Users className="h-3 w-3 mr-1" />
                        {data.team}
                      </Badge>
                    )}
                    <div className="text-sm text-muted-foreground">
                      Components: {data.components.join(', ')}
                    </div>
                  </div>
                  <Badge>{data.count} component{data.count !== 1 ? 's' : ''}</Badge>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {components.length > 0 && (
        <Card data-testid="components-card">
          <CardHeader>
            <CardTitle>All Components</CardTitle>
            <CardDescription>
              Services, APIs, and repositories tracked by ScopeDocs
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {components.map((component) => (
                <div key={component.id} className="p-4 border rounded-lg" data-testid={`component-item-${component.id}`}>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <p className="font-medium">{component.name}</p>
                      <Badge variant="outline">{component.type}</Badge>
                    </div>
                    {component.repo && (
                      <p className="text-xs text-muted-foreground">{component.repo}</p>
                    )}
                    {component.path && (
                      <p className="text-xs text-muted-foreground font-mono">{component.path}</p>
                    )}
                    <div className="text-xs text-muted-foreground">
                      Owners: {component.owners?.length || 0}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {(!ownership || Object.keys(ownership.ownership_distribution || {}).length === 0) && (
        <Card className="border-dashed" data-testid="no-ownership-card">
          <CardHeader>
            <CardTitle>No Ownership Data</CardTitle>
            <CardDescription>
              Generate mock data from the dashboard to see ownership information
            </CardDescription>
          </CardHeader>
        </Card>
      )}
    </div>
  );
};

export default Ownership;