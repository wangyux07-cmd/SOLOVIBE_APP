"""Short, source-bound public evidence; never stores extracted page bodies."""
from uuid import uuid4

from psycopg.types.json import Jsonb


class PublicEvidenceRepository:
    def __init__(self, pool):
        self.pool = pool

    async def persist(self, place, information):
        if not information['observations']:
            return
        async with self.pool.connection() as conn, conn.transaction():
            row = await (await conn.execute('''INSERT INTO solovibe_v1.venue_identity
                (venue_id,amap_poi_id,name,city,address,amap_coordinate)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (amap_poi_id) DO UPDATE SET
                name=excluded.name,city=excluded.city,address=excluded.address,
                amap_coordinate=excluded.amap_coordinate,updated_at=now()
                RETURNING venue_id''',
                (str(uuid4()), place['poi_id'], place['name'], place['city'],
                 place['address'], place['coordinate']))).fetchone()
            venue_id = row['venue_id']
            for observation in information['observations']:
                await conn.execute('''INSERT INTO solovibe_v1.source_observation
                    (observation_id,venue_id,kind,outcome,scope,source_url,observed_at,
                     content_sha256,evidence_excerpt,source_domain,extract_status,field_scope,content_length)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (observation_id) DO NOTHING''',
                    (observation['observation_id'],venue_id,observation['kind'],
                     observation['outcome'],observation['scope'],observation['url'],
                     observation['observed_at'],observation['content_sha256'],
                     observation['evidence_excerpt'],observation['source_domain'],
                     observation['extract_status'],observation['field_scope'],
                     observation['content_length']))
            for claim in information['claims']:
                await conn.execute('''INSERT INTO solovibe_v1.venue_claim
                    (claim_id,observation_id,venue_id,field,value,unit,scope,status,observed_at,valid_until)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (claim_id) DO NOTHING''',
                    (claim['claim_id'],claim['observation_id'],venue_id,claim['field'],
                     Jsonb(claim['value']),claim['unit'],claim['scope'],claim['status'],
                     claim['observed_at'],claim['valid_until']))
