import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scoring
import server

class ScoringTests(unittest.TestCase):
    def test_normalized_active_weights(self):
        weights = scoring.build_weights({'rice': True, 'people': 1})
        self.assertEqual(set(weights), {'rice','party_size_fit','rating','distance'})
        self.assertAlmostEqual(sum(weights.values()), 1)
        self.assertAlmostEqual(weights['rice'], 40/90)
        self.assertAlmostEqual(weights['party_size_fit'], 10/90)
        self.assertAlmostEqual(weights['rating'], 25/90)
        self.assertAlmostEqual(weights['distance'], 15/90)

    def test_rating_and_missing_data(self):
        for value in (None, 'bad', float('nan'), float('inf')):
            self.assertEqual(scoring.rating_to_score(value), .5)
        self.assertEqual(scoring.rating_to_score(3), 0)
        self.assertAlmostEqual(scoring.rating_to_score(4.1), .5)
        self.assertEqual(scoring.rating_to_score(5), 1)

    def test_low_tag_match_cannot_be_rescued_by_rating_distance_or_party_fit(self):
        restaurants = [dict(self.restaurants()[0], id=str(i), rating=5, distance_m=0)
                       for i in range(3)]
        def fake(payload):
            return {'answers': {
                'r0_healthy': {'noul': 0}, 'r0_party_size_fit': {'noul': 1},
                'r1_healthy': {'noul': .599}, 'r1_party_size_fit': {'noul': 1},
                'r2_healthy': {'noul': .6}, 'r2_party_size_fit': {'noul': .2},
            }}
        with patch.object(server, 'request_jev', fake):
            result = server.choose({'userPrefs': {'healthy': True, 'people': 3}}, restaurants)
        self.assertEqual(result['rankedIds'], ['2'])
        self.assertEqual(set(result['scores']), {'2'})
        self.assertEqual(set(result['jevScores']), {'2'})

    def test_all_tags_below_threshold_return_empty_success(self):
        with patch.object(server, 'request_jev', return_value={'answers': {
                'r0_meat': {'noul': .5}, 'r0_party_size_fit': {'noul': 1},
                'r1_meat': {'noul': .2}, 'r1_party_size_fit': {'noul': 1}}}):
            result = server.choose({'userPrefs': {'meat': True, 'people': 2}}, self.restaurants())
        self.assertIsNone(result['choiceId'])
        self.assertEqual(result['rankedIds'], [])
        self.assertEqual(result['scores'], {})

    def test_random_preference_has_no_tag_threshold(self):
        with patch.object(server, 'request_jev', return_value={'answers': {
                'r0_party_size_fit': {'noul': .1}, 'r1_party_size_fit': {'noul': .1}}}):
            result = server.choose({'userPrefs': {'people': 2}}, self.restaurants())
        self.assertEqual(result['rankedIds'], ['a', 'b'])

    def test_variety_excludes_western_fast_food_before_model(self):
        base = self.restaurants()[0]
        restaurants = [dict(base, id=str(i), name=name) for i, name in enumerate([
            '汉堡王(暖山生活店)', '麦当劳(奥运村店)', '肯德基车速取餐点',
            '赛百味 SUBWAY', '日式定食',
        ])]
        def fake(payload):
            self.assertEqual([r['name'] for r in payload['state']['restaurants'].values()], ['日式定食'])
            return {'answers': {'r0_variety': {'noul': .9}, 'r0_party_size_fit': {'noul': .8}}}
        with patch.object(server, 'request_jev', fake):
            result = server.choose({'userPrefs': {'variety': True, 'people': 2}}, restaurants)
        self.assertEqual(result['rankedIds'], ['4'])
        self.assertEqual(set(result['scores']), {'4'})
        with patch.object(server, 'request_jev', side_effect=AssertionError('no candidates')):
            empty = server.choose({'userPrefs': {'variety': True, 'people': 2}}, restaurants[:4])
            self.assertEqual(empty['rankedIds'], [])
            self.assertIsNone(empty['choiceId'])

    def test_western_fast_food_remains_available_under_other_tags(self):
        restaurant = dict(self.restaurants()[0], name='汉堡王(暖山生活店)')
        with patch.object(server, 'request_jev', return_value={'answers': {
                'r0_quick_meal': {'noul': .9}, 'r0_party_size_fit': {'noul': .9}}}):
            result = server.choose({'userPrefs': {'quick_meal': True, 'people': 2}}, [restaurant])
        self.assertEqual(result['rankedIds'], ['a'])
        self.assertFalse(scoring.is_western_fast_food({'name': '日式定食', 'cuisine': '快餐厅'}))
        self.assertFalse(scoring.is_western_fast_food({'name': '韩式拌饭', 'cuisine': '韩式快餐'}))

    def test_legacy_spice_preferences_are_ignored(self):
        payload = {'preferences': {'people': 3, 'minBudget': 15, 'maxBudget': 100,
                                   'preferredTag': '重口的'},
                   'restaurants': self.restaurants()}
        current, restaurants = server.valid_request(payload)
        payload['preferences'].update(spice=0, spiciness=5)
        legacy, _ = server.valid_request(payload)
        self.assertEqual(current, legacy)
        questions = scoring.build_questions(restaurants, legacy['userPrefs'])
        self.assertTrue(all(q['type'] == 'noul' for q in questions.values()))
        self.assertEqual(len(questions), 4)
        self.assertFalse(any('spiciness' in key for key in questions))
        weights = scoring.build_weights({'people': 3, 'heavy_flavor': True, 'spiciness': 5})
        self.assertNotIn('spiciness', weights)
        score = scoring.calculate_score(restaurants[0], {'heavy_flavor': .8, 'party_size_fit': .8},
                                        {'people': 3, 'heavy_flavor': True})
        legacy_score = scoring.calculate_score(restaurants[0],
                                               {'heavy_flavor': .8, 'party_size_fit': .8, 'spiciness': 5},
                                               {'people': 3, 'heavy_flavor': True, 'spiciness': 0})
        self.assertEqual(score, legacy_score)

    def test_inactive_dimensions_redistribute_weights(self):
        weights = scoring.build_weights({'healthy': True, 'people': 3})
        self.assertEqual(set(weights), {'healthy', 'party_size_fit', 'rating', 'distance'})
        self.assertAlmostEqual(weights['healthy'], 40/90)
        self.assertAlmostEqual(weights['rating'], 25/90)
        self.assertAlmostEqual(weights['distance'], 15/90)
        self.assertAlmostEqual(weights['party_size_fit'], 10/90)
        random_weights = scoring.build_weights({'people': 3})
        self.assertEqual(random_weights, {'party_size_fit': .2, 'rating': .5, 'distance': .3})

    def test_all_nine_tags_reach_model_and_weighted_ranking(self):
        tags = [('米饭', 'rice'), ('面食', 'noodles'), ('带汤的', 'soup'),
                ('健康的', 'healthy'), ('放纵的', 'indulgent'), ('重口的', 'heavy_flavor'),
                ('吃肉', 'meat'), ('换个口味', 'variety'), ('快餐', 'quick_meal')]
        for tag, field in tags:
            with self.subTest(tag=tag):
                prefs, restaurants = server.valid_request({
                    'preferences': {'people': 2, 'minBudget': 15, 'maxBudget': 100,
                                    'preferredTag': tag},
                    'restaurants': self.restaurants()[:1],
                })
                def fake(payload):
                    self.assertEqual(set(payload['questions']), {f'r0_{field}', 'r0_party_size_fit'})
                    self.assertEqual(payload['questions'][f'r0_{field}']['type'], 'noul')
                    return {'answers': {f'r0_{field}': {'noul': .8}, 'r0_party_size_fit': {'noul': .8}}}
                with patch.object(server, 'request_jev', fake):
                    result = server.choose(prefs, restaurants)
                self.assertEqual(result['source'], 'jev-weighted')
                self.assertEqual(result['rankedIds'], ['a'])
                self.assertAlmostEqual(result['weights'][field], 40/90)
                self.assertAlmostEqual(result['scores']['a'], 80/90)

    def test_distance_can_outweigh_moderate_rating_difference(self):
        restaurants = self.restaurants()
        restaurants[0].update(rating=4.28, distance_m=300)
        restaurants[1].update(rating=4.7, distance_m=2000)
        with patch.object(server, 'request_jev', return_value={'answers': {
                'r0_party_size_fit': {'noul': .5}, 'r1_party_size_fit': {'noul': .5}}}):
            result = server.choose({'userPrefs': {'people': 3}}, restaurants)
        self.assertEqual(result['rankedIds'], ['a', 'b'])
        self.assertAlmostEqual(result['scores']['a'], .725)
        self.assertAlmostEqual(result['scores']['b'], .645)

    def test_distance_boundaries(self):
        for value, expected in [(300,1),(301,.85),(600,.85),(601,.65),(1000,.65),(1001,.35),(1500,.35),(1501,.15),(2000,.15),(2001,0),(None,.5)]:
            self.assertEqual(scoring.distance_to_score(value), expected)

    def restaurants(self):
        return [{'id':'a','name':'A','cuisine':'面食','price':30,'minPeople':1,'maxPeople':4,'rating':4.7,'distance_m':300}, {'id':'b','name':'B','cuisine':'简餐','price':30,'minPeople':1,'maxPeople':4,'rating':3.5,'distance_m':2100}]

    def test_preferences_and_preserved_metadata(self):
        prefs, restaurants = server.valid_request({'preferences':{'people':1,'minBudget':15,'maxBudget':100,'preferredTag':'面食'},'restaurants':self.restaurants()})
        self.assertEqual(prefs['userPrefs']['people'], 1)
        self.assertTrue(prefs['userPrefs']['noodles'])
        self.assertEqual(restaurants[0]['distance_m'],300)
        self.assertEqual(len(restaurants),2)

    def test_question_parsing_and_ranking(self):
        prefs = {'userPrefs': {'noodles': True, 'people': 2}}
        def fake(payload):
            self.assertTrue(all(q['type'] == 'noul' for q in payload['questions'].values()))
            return {'model': 'test', 'answers': {
                'r0_noodles': {'noul': .9}, 'r0_party_size_fit': {'noul': .8},
                'r1_noodles': {'noul': .1}, 'r1_party_size_fit': {'noul': .2},
            }}
        with patch.object(server, 'request_jev', fake):
            result = server.choose(prefs, self.restaurants())
        self.assertEqual(result['rankedIds'], ['a'])
        self.assertEqual(result['choiceId'], 'a')
        self.assertNotIn('probabilities', result)
        self.assertAlmostEqual(result['scores']['a'], (0.9*40 + .8*10 + 25 + 15)/90)

    def test_random_group_still_evaluates_party_size(self):
        def fake(payload):
            self.assertEqual(set(payload['questions']), {'r0_party_size_fit', 'r1_party_size_fit'})
            return {'answers': {'r0_party_size_fit': {'noul': .8}, 'r1_party_size_fit': {'noul': .8}}}
        with patch.object(server, 'request_jev', fake):
            result=server.choose({'userPrefs':{'people':3}},self.restaurants())
        self.assertEqual(result['source'],'jev-weighted')
        self.assertEqual(result['choiceId'],'a')

    def test_complex_preferences_limit_questions_per_call(self):
        restaurants = [dict(self.restaurants()[0], id=str(index)) for index in range(25)]
        calls = []
        def fake(payload):
            calls.append(payload)
            answers = {}
            for question_id, question in payload["questions"].items():
                answers[question_id] = {"noul": 0.8}
            return {"model": "test", "answers": answers}
        with patch.object(server, "request_jev", fake):
            result = server.choose({"userPrefs": {"rice": True, "people": 1}}, restaurants)
        self.assertEqual(len(calls), 4)
        self.assertEqual(len(result["scores"]), 25)

    def test_actual_party_size_reaches_model_and_changes_ranking(self):
        restaurants = [
            dict(self.restaurants()[0], id='set', name='单人套餐', cuisine='快餐',
                 dishes='单人套餐', minPeople=None, maxPeople=None),
            dict(self.restaurants()[0], id='shared', name='共享小炒', cuisine='中餐',
                 dishes='点菜、共享菜、大份菜', minPeople=None, maxPeople=None),
        ]
        for people in (1, 2, 3, 4, 6, 12):
            with self.subTest(people=people):
                prefs, clean = server.valid_request({
                    'preferences': {'people': people, 'minBudget': 15, 'maxBudget': 100,
                                    'preferredTag': ''},
                    'restaurants': restaurants,
                })
                self.assertEqual(prefs['userPrefs']['people'], people)
                def fake(payload):
                    for question in payload['questions'].values():
                        self.assertIn(f'a lunch party of {people} people', question['instructions'])
                    # Controlled model outputs verify score integration, not model inference.
                    individual, shared = (.95, .3) if people <= 2 else (.4, .9)
                    return {'answers': {'r0_party_size_fit': {'noul': individual},
                                        'r1_party_size_fit': {'noul': shared}}}
                with patch.object(server, 'request_jev', fake):
                    result = server.choose(prefs, clean)
                self.assertEqual(result['choiceId'], 'set' if people <= 2 else 'shared')
                self.assertAlmostEqual(result['weights']['party_size_fit'], .2)

    def test_known_capacity_still_filters_before_model(self):
        with self.assertRaises(ValueError):
            server.valid_request({
                'preferences': {'people': 6, 'minBudget': 15, 'maxBudget': 100,
                                'preferredTag': ''},
                'restaurants': self.restaurants(),
            })

    def test_missing_party_size_answer_fails_instead_of_silently_skipping(self):
        with patch.object(server, 'request_jev', return_value={'answers': {}}):
            with self.assertRaises(RuntimeError):
                server.choose({'userPrefs': {'people': 3}}, self.restaurants())

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
                server.choose({'userPrefs':{'rice':True,'people':2}},self.restaurants())

if __name__=='__main__':
    unittest.main()
