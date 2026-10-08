import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scoring
import server

class ScoringTests(unittest.TestCase):
    def test_normalized_active_weights(self):
        weights = scoring.build_weights({'rice': True, 'solo': True, 'spiciness': 0})
        self.assertEqual(set(weights), {'rice','solo_friendly','spiciness','rating','distance'})
        self.assertAlmostEqual(sum(weights.values()), 1)
        self.assertAlmostEqual(weights['rating'], .8/4.3)
        self.assertNotIn('spiciness', scoring.build_weights({'spiciness': None}))

    def test_rating_and_missing_data(self):
        for value in (None, 'bad', float('nan'), float('inf')):
            self.assertEqual(scoring.rating_to_score(value), .5)
        self.assertEqual(scoring.rating_to_score(3), 0)
        self.assertAlmostEqual(scoring.rating_to_score(4.1), .5)
        self.assertEqual(scoring.rating_to_score(5), 1)

    def test_distance_boundaries(self):
        for value, expected in [(300,1),(301,.85),(600,.85),(601,.65),(1000,.65),(1001,.35),(1500,.35),(1501,.15),(2000,.15),(2001,0),(None,.5)]:
            self.assertEqual(scoring.distance_to_score(value), expected)

    def test_spice_matching(self):
        self.assertEqual(scoring.spiciness_match(2,2),1)
        self.assertEqual(scoring.spiciness_match(3,2),.75)
        self.assertEqual(scoring.spiciness_match(5,0),0)
        self.assertEqual(scoring.spiciness_match(None,0),0)

    def restaurants(self):
        return [{'id':'a','name':'A','cuisine':'面食','price':30,'minPeople':1,'maxPeople':4,'spice':5,'rating':4.7,'distance_m':300}, {'id':'b','name':'B','cuisine':'简餐','price':30,'minPeople':1,'maxPeople':4,'spice':0,'rating':3.5,'distance_m':2100}]

    def test_soft_spice_and_preserved_metadata(self):
        prefs, restaurants = server.valid_request({'preferences':{'people':1,'minBudget':15,'maxBudget':100,'spice':0,'preferredTag':'面食'},'restaurants':self.restaurants()})
        self.assertTrue(prefs['userPrefs']['solo'])
        self.assertTrue(prefs['userPrefs']['noodles'])
        self.assertEqual(restaurants[0]['distance_m'],300)
        self.assertEqual(len(restaurants),2) # Spice is weighted rather than a hard exclusion.

    def test_question_parsing_and_ranking(self):
        prefs={'userPrefs':{'noodles':True,'spiciness':0}}
        def fake(payload):
            self.assertEqual(payload['questions']['r0_noodles']['type'],'noul')
            self.assertEqual(len(payload['questions']['r0_spiciness']['criteria']),6)
            return {'model':'test', 'answers':{'r0_noodles':{'noul':.9},'r0_spiciness':{'score':0},'r1_noodles':{'noul':.1},'r1_spiciness':{'score':5}}}
        with patch.object(server,'request_jev',fake):
            result=server.choose(prefs,self.restaurants())
        self.assertEqual(result['rankedIds'],['a','b'])
        self.assertEqual(result['choiceId'],'a')
        self.assertNotIn('probabilities',result)
        self.assertAlmostEqual(result['scores']['a'],(0.9+1+0.8+0.5)/3.3)

    def test_random_group_uses_local_dimensions_only(self):
        with patch.object(server,'request_jev',side_effect=AssertionError('unneeded API request')):
            result=server.choose({'userPrefs':{'spiciness':None}},self.restaurants())
        self.assertEqual(result['source'],'local-weighted')
        self.assertEqual(result['choiceId'],'a')

    def test_complex_preferences_limit_questions_per_call(self):
        restaurants = [dict(self.restaurants()[0], id=str(index)) for index in range(25)]
        calls = []
        def fake(payload):
            calls.append(payload)
            self.assertLessEqual(len(payload["questions"]), 15)
            answers = {}
            for question_id, question in payload["questions"].items():
                answers[question_id] = {"score": 2} if question["type"] == "score" else {"noul": 0.8}
            return {"model": "test", "answers": answers}
        with patch.object(server, "request_jev", fake):
            result = server.choose({"userPrefs": {"rice": True, "solo": True, "spiciness": 2}}, restaurants)
        self.assertEqual(len(calls), 5)
        self.assertEqual(len(result["scores"]), 25)

    def test_temporary_jev_disconnect_is_retried(self):
        from io import BytesIO
        from urllib.error import URLError
        response = BytesIO(b"{\"answers\": {}}")
        with patch.object(server, "api_key", return_value="test"), \
             patch.object(server, "urlopen", side_effect=[URLError("reset"), response]) as send, \
             patch.object(server.time, "sleep"):
            result = server.request_jev({"model": "test"})
        self.assertEqual(result, {"answers": {}})
        self.assertEqual(send.call_count, 2)

    def test_temporary_jev_405_is_retried(self):
        from io import BytesIO
        from urllib.error import HTTPError
        method_error = HTTPError(server.API_URL, 405, "Method Not Allowed", {}, BytesIO(b""))
        response = BytesIO(b"{\"answers\": {}}")
        with patch.object(server, "api_key", return_value="test"), \
             patch.object(server, "urlopen", side_effect=[method_error, response]) as send, \
             patch.object(server.time, "sleep"):
            result = server.request_jev({"model": "test"})
        self.assertEqual(result, {"answers": {}})
        self.assertEqual(send.call_count, 2)
        self.assertEqual(send.call_args.args[0].get_method(), "POST")

    def test_incomplete_api_answers_fail(self):
        with patch.object(server,'request_jev',return_value={'answers':{}}):
            with self.assertRaises(RuntimeError):
                server.choose({'userPrefs':{'rice':True}},self.restaurants())

if __name__=='__main__':
    unittest.main()
