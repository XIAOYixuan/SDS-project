from utils.domain.jsonlookupdomain import JSONLookupDomain

domain = JSONLookupDomain('Courses')
res = domain.query_db("SELECT * FROM Courses")
print(res)