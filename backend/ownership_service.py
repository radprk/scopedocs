from typing import List, Dict, Any
from backend.models import Component, Person, Relationship, RelationshipType
from backend.database import db, COLLECTIONS

class OwnershipService:
    """Service for tracking ownership across systems"""
    
    async def resolve_ownership(self, component_id: str) -> Dict[str, Any]:
        """Resolve ownership for a component"""
        component = await db[COLLECTIONS['components']].find_one({'id': component_id})
        if not component:
            return {'error': 'Component not found'}
        
        # Get ownership relationships
        ownership_rels = await db[COLLECTIONS['relationships']].find({
            'target_id': component_id,
            'relationship_type': RelationshipType.OWNS
        }).to_list(100)
        
        # Get person details
        owner_ids = [rel['source_id'] for rel in ownership_rels]
        owners = await db[COLLECTIONS['people']].find(
            {'external_id': {'$in': owner_ids}}
        ).to_list(100)
        
        # Calculate confidence
        ownership_info = []
        for rel in ownership_rels:
            owner = next((o for o in owners if o['external_id'] == rel['source_id']), None)
            if owner:
                ownership_info.append({
                    'person': owner['name'],
                    'team': owner.get('team'),
                    'confidence': rel['confidence'],
                    'evidence': rel.get('evidence', [])
                })
        
        return {
            'component': component['name'],
            'type': component['type'],
            'owners': ownership_info
        }
    
    async def find_component_owners(self, repo: str, path: str = None) -> List[str]:
        """Find owners of a component based on repo/path"""
        query = {'repo': repo}
        if path:
            query['path'] = {'$regex': f'^{path}'}
        
        components = await db[COLLECTIONS['components']].find(query).to_list(100)
        
        all_owners = set()
        for comp in components:
            all_owners.update(comp.get('owners', []))
        
        return list(all_owners)
    
    async def get_ownership_summary(self) -> Dict[str, Any]:
        """Get overall ownership summary"""
        components = await db[COLLECTIONS['components']].find({}).to_list(1000)
        people = await db[COLLECTIONS['people']].find({}).to_list(1000)
        
        # Count components per person
        ownership_counts = {}
        for person in people:
            count = sum(1 for comp in components if person['external_id'] in comp.get('owners', []))
            if count > 0:
                ownership_counts[person['name']] = {
                    'count': count,
                    'team': person.get('team'),
                    'components': [comp['name'] for comp in components if person['external_id'] in comp.get('owners', [])]
                }
        
        return {
            'total_components': len(components),
            'total_people': len(people),
            'ownership_distribution': ownership_counts
        }
